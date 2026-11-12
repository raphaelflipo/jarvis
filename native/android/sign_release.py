#!/usr/bin/env python3
"""Signe un APK avec une clé existante ; aucun secret n'est écrit dans le paquet."""
import argparse
import os
from pathlib import Path
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('apk',type=Path)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--keystore',type=Path,required=True)
parser.add_argument('--apksigner',type=Path,required=True,help='Chemin vers apksigner.jar officiel')
args=parser.parse_args()
if not os.environ.get('JARVIS_ANDROID_STORE_PASSWORD'):
    raise SystemExit('La variable JARVIS_ANDROID_STORE_PASSWORD est requise.')
args.output.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['java','-jar',str(args.apksigner),'sign','--ks',str(args.keystore),'--ks-key-alias','jarvis-release','--ks-pass','env:JARVIS_ANDROID_STORE_PASSWORD','--key-pass','env:JARVIS_ANDROID_STORE_PASSWORD','--out',str(args.output),str(args.apk)],check=True)
subprocess.run(['java','-jar',str(args.apksigner),'verify','--verbose','--print-certs',str(args.output)],check=True)
