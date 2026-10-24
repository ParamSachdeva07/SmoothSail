"""Upload selected server secrets through stdin, then deploy the Worker/container."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

from dotenv import dotenv_values, set_key

from service.config import ROOT, settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', help='Node.js 22+ executable; defaults to NODE_BINARY or PATH.')
    args = parser.parse_args()
    local = dotenv_values(ROOT / '.env')
    node = args.node or local.get('NODE_BINARY') or shutil.which('node')
    if not node or int(subprocess.check_output([node, '-p', 'process.versions.node.split(".")[0]'], text=True)) < 22:
        parser.error('Node.js 22+ is required; set NODE_BINARY or use --node.')
    directory = ROOT / 'cloudflare'
    cli = directory / 'node_modules/wrangler/bin/wrangler.js'
    if not cli.exists():
        parser.error('Run npm ci inside cloudflare/ first.')
    env = os.environ | {'PATH': str(Path(node).parent) + os.pathsep + os.environ['PATH']}
    command = [node, str(cli)]
    # Stop before uploading credentials or creating resources if Containers is unavailable.
    subprocess.run(command + ['containers', 'list'], cwd=directory, env=env, check=True)
    uri = settings.connection_uri()
    if not uri.startswith('mongodb+srv://'):
        parser.error('Configure the Atlas MONGODB_URI before cloud deployment.')
    if not settings.copernicus_username or not settings.copernicus_password.get_secret_value():
        parser.error('Configure Copernicus Marine credentials for scheduled cloud refreshes.')
    token = settings.tideline_internal_token.get_secret_value()
    if not token:
        token = secrets.token_urlsafe(32)
        set_key(ROOT / '.env', 'TIDELINE_INTERNAL_TOKEN', token)
    values = {
        'MONGODB_URI': uri,
        'COPERNICUS_USERNAME': settings.copernicus_username,
        'COPERNICUS_PASSWORD': settings.copernicus_password.get_secret_value(),
        'TIDELINE_INTERNAL_TOKEN': token,
    }
    if settings.gemini_api_key.get_secret_value():
        values['GEMINI_API_KEY'] = settings.gemini_api_key.get_secret_value()
    subprocess.run(command + ['secret', 'bulk'], cwd=directory, env=env,
                   input=json.dumps(values), text=True, check=True)
    subprocess.run(command + ['deploy'], cwd=directory, env=env, check=True)


if __name__ == '__main__':
    main()
