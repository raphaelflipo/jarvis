#!/usr/bin/env python3
"""Construit Jarvis.app autonome et un DMG ; ne copie aucun profil utilisateur."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
VERSION='3.3.0-rc.1'
SOURCES={
 'python':('https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-aarch64-apple-darwin-install_only_stripped.tar.gz','2f11b8aa3726bdbd87dd9eb76568412faddf4f47e26913fa45d6a2e424972acd'),
 'ollama':('https://github.com/ollama/ollama/releases/download/v0.40.16/ollama-darwin.tgz','a743717494315da7cd352982b805f6b992d4b4452ca117fd5fbf86c4ee46fca0')}

def run(*args,**kwargs): subprocess.run(args,check=True,**kwargs)
def build(cache:Path,output:Path):
    output.mkdir(parents=True,exist_ok=True)
    stage=output/'macOS';stage.mkdir(exist_ok=True)
    app=stage/'Jarvis.app'
    if app.exists(): shutil.rmtree(app)
    resources=app/'Contents/Resources';binary=app/'Contents/MacOS'
    resources.mkdir(parents=True);binary.mkdir()
    python=cache/'runtime/python';ollama=cache/'ollama';browsers=cache/'chromium'
    for folder in [python,ollama,browsers]:
        if not folder.is_dir(): raise SystemExit(f'Dépendance manquante : {folder}. Voir native/BUILD.md.')
    for key,filename in [('python','python-macos.tar.gz'),('ollama','ollama-macos.tgz')]:
        digest=hashlib.file_digest((cache/'downloads'/filename).open('rb'),'sha256').hexdigest()
        if digest!=SOURCES[key][1]: raise SystemExit(f'Archive {key} non conforme')
    for source,name in [(python,'python'),(ollama,'ollama'),(browsers,'browsers')]:
        shutil.copytree(source,resources/name,symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
    # Les commandes Python restent exécutables après déplacement de l'application.
    for script in (resources/'python/bin').iterdir():
        if script.is_symlink() or not script.is_file(): continue
        data=script.read_bytes()
        if data.startswith(b'#!') and b'python' in data.split(b'\n',1)[0]:
            body=data.split(b'\n',1)[1]
            script.write_bytes(b'''#!/bin/sh
''' + b"'''exec' \"$(dirname \"$0\")/python3\" \"$0\" \"$@\"\n' '''\n" + body)
    from build_macos import RUNTIME_MODULES,WEB_ASSETS
    backend=resources/'backend';(backend/'web').mkdir(parents=True)
    for name in RUNTIME_MODULES: shutil.copy2(ROOT/'jarvis'/f'{name}.py',backend/f'{name}.py')
    for name in WEB_ASSETS: shutil.copy2(ROOT/'jarvis/web'/name,backend/'web'/name)
    for name,frameworks in [('JarvisApp',['Cocoa','WebKit','Carbon','EventKit']),('JarvisAgenda',['EventKit'])]:
        args=['xcrun','swiftc','-O','-target','arm64-apple-macos14.0',str(ROOT/'macos'/f'{name}.swift'),'-o',str(binary/('Jarvis' if name=='JarvisApp' else 'jarvis-agenda'))]
        for framework in frameworks: args+=['-framework',framework]
        run(*args)
    shutil.copy2(ROOT/'assets/AppIcon.icns',resources/'AppIcon.icns')
    shutil.copy2(ROOT/'LICENSE',resources/'LICENSE')
    shutil.copy2(ROOT/'requirements-macos.lock',resources/'requirements-macos.lock')
    notices=resources/'THIRD-PARTY-NOTICES.txt'
    notices.write_text('Jarvis — MIT. Dépendances redistribuées avec leurs licences intégrées.\nPython 3.12.16 (PSF), python-build-standalone 20261110, Ollama 0.40.16 (MIT), Chromium/Playwright et paquets Python : consulter leurs fichiers LICENSE et dist-info/licenses.\nAucun modèle inclus : le téléchargement initial est proposé dans le menu Jarvis.\nSources des moteurs : https://github.com/astral-sh/python-build-standalone ; https://github.com/ollama/ollama ; https://github.com/microsoft/playwright\n')
    info={'CFBundleIdentifier':'local.jarvis.app','CFBundleExecutable':'Jarvis','CFBundleName':'Jarvis','CFBundleDisplayName':'Jarvis','CFBundlePackageType':'APPL','CFBundleIconFile':'AppIcon','CFBundleShortVersionString':'3.3.0','CFBundleVersion':'33001','LSMinimumSystemVersion':'14.0','NSHighResolutionCapable':True,'NSCalendarsFullAccessUsageDescription':'Jarvis accède au calendrier uniquement pour les tâches que vous lui demandez.','NSRemindersFullAccessUsageDescription':'Jarvis accède aux rappels pour les tâches que vous lui demandez.','NSAppleEventsUsageDescription':'Jarvis peut piloter les applications autorisées pour réaliser vos demandes.','NSCameraUsageDescription':'Jarvis utilise la caméra uniquement sur votre demande.','NSMicrophoneUsageDescription':'Jarvis utilise le microphone si vous activez la voix.'}
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    (resources/'BUILD.json').write_text(json.dumps({'version':VERSION,'commit':commit,'architecture':'arm64','dependencies':SOURCES,'signature':'ad-hoc; not notarized'},indent=2))
    # Retire uniquement les métadonnées Finder incompatibles avec la signature du paquet.
    for attribute in ('com.apple.FinderInfo','com.apple.ResourceFork'):
        subprocess.run(['xattr','-dr',attribute,str(app)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    # Signe les exécutables et bibliothèques imbriqués avant le conteneur.
    signed=set()
    for path in sorted(app.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if path.is_symlink() or not path.is_file(): continue
        with path.open('rb') as f: magic=f.read(4)
        if magic in [b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca']:
            real=path.resolve()
            if real in signed: continue
            run('codesign','--force','--sign','-',str(path),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);signed.add(real)
    for container in sorted([p for p in app.rglob('*') if p.suffix in ('.app','.framework') and p.is_dir()],key=lambda p:len(p.parts),reverse=True):
        run('codesign','--force','--sign','-',str(container))
    run('codesign','--force','--sign','-',str(app))
    run('codesign','--verify','--deep','--strict',str(app))
    link=stage/'Applications'
    if not link.exists(): link.symlink_to('/Applications')
    target=output/f'Jarvis-{VERSION}-macOS-arm64.dmg'
    target.unlink(missing_ok=True)
    run('hdiutil','create','-volname','Jarvis','-srcfolder',str(stage),'-format','UDZO','-o',str(target))
    digest=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
    target.with_suffix('.dmg.sha256').write_text(f'{digest}  {target.name}\n')
    print(target)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cache',type=Path,required=True);parser.add_argument('--output',type=Path,default=ROOT/'dist')
    args=parser.parse_args();build(args.cache.resolve(),args.output.resolve())
