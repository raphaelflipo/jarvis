"""Prépare les ressources natives à partir de local-app, source unique de l'interface."""
from pathlib import Path
import shutil
import json
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
for platform, target in [('windows',ROOT/'native/windows/app'),('android',ROOT/'native/android/app/src/main/assets/app'),('ios',ROOT/'native/ios/app')]:
    if target.exists(): shutil.rmtree(target)
    shutil.copytree(ROOT/'local-app',target,ignore=shutil.ignore_patterns('package.json','README.md','node_modules','*.map'))
shutil.copy2(ROOT/'native/common/selftest.js',ROOT/'native/windows/selftest.js')
shutil.copy2(ROOT/'native/common/selftest.js',ROOT/'native/ios/selftest.js')
icon=Image.open(ROOT/'assets/icon_1024.png').convert('RGBA')
icon.save(ROOT/'native/windows/icon.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
for name,size in [('mdpi',48),('hdpi',72),('xhdpi',96),('xxhdpi',144),('xxxhdpi',192)]:
    d=ROOT/f'native/android/app/src/main/res/mipmap-{name}';d.mkdir(parents=True,exist_ok=True)
    icon.resize((size,size),Image.Resampling.LANCZOS).save(d/'ic_launcher.png')
d=ROOT/'native/ios/Assets.xcassets/AppIcon.appiconset';d.mkdir(parents=True,exist_ok=True)
icon.convert('RGB').save(d/'AppIcon.png')
(d/'Contents.json').write_text(json.dumps({'images':[{'filename':'AppIcon.png','idiom':'universal','platform':'ios','size':'1024x1024'}],'info':{'author':'Raphaël Flipo','version':1}}))
(ROOT/'native/ios/Assets.xcassets/Contents.json').write_text('{"info":{"version":1,"author":"Raphaël Flipo"}}')
print('Ressources natives synchronisées.')

d=ROOT/"native/android/app/src/androidTest/assets";d.mkdir(parents=True,exist_ok=True)
shutil.copy2(ROOT/"native/common/selftest.js",d/"selftest.js")

shutil.copy2(ROOT/'native/common/ui-selftest.js',ROOT/'native/windows/ui-selftest.js')
