"""Linux/Docker manual check: python3 tests/drill_deploy.py ops/deploy.py

Exercise the actual deployment receiver with isolated Docker Compose resources.
Registry authentication is excluded: both fixture images must already be local.
"""
import importlib.util, io, json, pathlib, socket, subprocess, sys, tempfile, uuid
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('deploy',sys.argv[1])
deploy=importlib.util.module_from_spec(spec); spec.loader.exec_module(deploy)
previous='ghcr.io/zeraigr/media-knowledge-server@sha256:8a8de16323572650849d2aa0dedf52dbe72d91107e4e36f1d8150b40b3ec4549'
candidate='ghcr.io/zeraigr/media-knowledge-web@sha256:a90f0aba125a6019be486bbbea3184049d6a3f12c72337c0f01bded1f55bce62'
postgres='postgres@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94'
run=subprocess.run
for image in [previous,candidate,postgres]:run(['docker','image','inspect',image],check=True,stdout=subprocess.DEVNULL)
with tempfile.TemporaryDirectory(prefix='mk-rollback-drill-') as d:
 root=pathlib.Path(d)
 with socket.socket() as sock:sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
 project='mk-rollback-drill-'+uuid.uuid4().hex[:10]
 images=root/'images.env'; before='SERVER_IMAGE='+previous+'\n'; images.write_text(before)
 (root/'secrets.env').write_text('POSTGRES_PASSWORD=synthetic-drill-only\n')
 (root/'compose.yaml').write_text('''name: '''+project+'''
services:
  db:
    image: '''+postgres+'''
    environment:
      POSTGRES_USER: media
      POSTGRES_DB: media
      POSTGRES_PASSWORD: synthetic-drill-only
    healthcheck:
      test: [CMD-SHELL, pg_isready -U media -d media]
      interval: 1s
      timeout: 2s
      retries: 30
    mem_limit: 128m
  api:
    image: ${SERVER_IMAGE}
    entrypoint: [/api]
    environment:
      DATABASE_URL: postgres://media:synthetic-drill-only@db:5432/media?sslmode=disable
    ports: ["127.0.0.1:'''+str(port)+''':8080"]
    read_only: true
    mem_limit: 128m
''')
 compose=['docker','compose','--project-directory',d,'--env-file',str(root/'secrets.env'),'--env-file',str(images),'-f',str(root/'compose.yaml')]
 def local_images(args,**kw):
  if args[:2] in [['docker','login'],['docker','pull']]:return subprocess.CompletedProcess(args,0)
  return run(args,**kw)
 try:
  run(compose+['up','-d','--wait','db'],check=True)
  run(compose+['up','-d','--no-deps','api'],check=True)
  deploy.wait_ready(port,'/readyz')
  request=io.TextIOWrapper(io.BytesIO(json.dumps({'digest':candidate.split('@')[1],'token':'synthetic-unused'}).encode()))
  with patch.object(deploy,'ROOT',root),patch.object(deploy,'IMAGES',images),patch.object(deploy,'REPOS',{'server':('api','SERVER_IMAGE','media-knowledge-web',port,'/readyz')}),patch.object(deploy.subprocess,'run',side_effect=local_images),patch('sys.argv',['deploy','server']),patch('sys.stdin',request):
   try:deploy.main()
   except (RuntimeError, subprocess.CalledProcessError):pass
   else:raise AssertionError('bad fixture unexpectedly became ready')
  assert images.read_text()==before
  deploy.wait_ready(port,'/readyz')
  cid=subprocess.check_output(compose+['ps','-q','api'],text=True).strip()
  actual=subprocess.check_output(['docker','inspect',cid,'--format','{{.Config.Image}}'],text=True).strip()
  assert actual==previous
  print(json.dumps({'isolated':True,'productionTouched':False,'candidateRejected':True,'previousImageRestored':True,'rollbackReady':True,'registryAuthTested':False}))
 finally:
  run(compose+['down','--volumes','--remove-orphans'],check=True)
