# app.py
from flask import Flask, request, send_from_directory, jsonify, send_file
import subprocess
import os
import re
import shutil
import zipfile
import io
import json
import sys
from pathlib import Path
from werkzeug.exceptions import HTTPException
from datetime import datetime

app = Flask(__name__)

# base dirs
PROJECTS_DIR = os.path.join(app.root_path, 'projects')
GIT_CONFIG_DIR = os.path.join(app.root_path, 'git_config')
os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(GIT_CONFIG_DIR, exist_ok=True)

# ----------------- Serve dashboard/editor + favicon -----------------
@app.route('/', methods=['GET'])
def dashboard_page():
    """Serve dashboard.html from the application directory."""
    return send_from_directory(app.root_path, 'dashboard.html')

@app.route('/editor', methods=['GET'])
def editor_page():
    """Serve editor page."""
    return send_from_directory(app.root_path, 'editor.html')

@app.route('/favicon.ico')
def favicon():
    fav_path = os.path.join(app.root_path, 'favicon.ico')
    if os.path.exists(fav_path):
        return send_from_directory(app.root_path, 'favicon.ico')
    # no favicon available — return no content
    return ('', 204)

# ----------------- Request logging (helpful for debugging) -----------------
@app.before_request
def log_request_info():
    ts = datetime.utcnow().isoformat() + "Z"
    method = request.method
    path = request.path
    remote = request.remote_addr
    ua = request.headers.get('User-Agent', '')[:120]
    print(f"[{ts}] {remote} {method} {path} UA={ua}", file=sys.stdout, flush=True)

# ----------------- Helpers -----------------
def sanitize_name(name):
    if not name:
        return None
    s = str(name).strip()
    s = re.sub(r'\s+', '_', s)
    s = re.sub(r'[^a-zA-Z0-9_.-]', '', s)
    if '..' in s or s.startswith(('/', '.')):
        return None
    return s

def get_project_path(project_name):
    safe = sanitize_name(project_name)
    return None if not safe else os.path.join(PROJECTS_DIR, safe)

def get_file_path(project_name, file_name):
    project_path = get_project_path(project_name)
    safe_file = sanitize_name(file_name)
    if not project_path or not safe_file:
        return None
    return os.path.join(project_path, safe_file)

def get_pdf_path(project_name, file_name):
    fp = get_file_path(project_name, file_name)
    if not fp:
        return None
    pdf_name = os.path.splitext(os.path.basename(fp))[0] + '.pdf'
    return os.path.join(os.path.dirname(fp), pdf_name)

# ----------------- Test endpoint (detect method rewriting) -----------------
@app.route('/api/test_method', methods=['GET', 'POST', 'DELETE', 'PUT', 'OPTIONS'])
def test_method():
    return jsonify({
        'received_method': request.method,
        'path': request.path,
        'remote_addr': request.remote_addr,
        'user_agent': request.headers.get('User-Agent', ''),
        'note': 'If DELETE from the browser returns something else, a proxy may rewrite methods.'
    })

# ----------------- Projects (list/create) -----------------
@app.route('/api/projects', methods=['GET', 'POST'])
def projects_root():
    if request.method == 'GET':
        projects = [entry.name for entry in os.scandir(PROJECTS_DIR) if entry.is_dir()]
        return jsonify(projects)

    data = request.get_json(silent=True) or {}
    raw = data.get('name')
    if not raw:
        return jsonify({'error': 'Project name required'}), 400
    project = sanitize_name(raw)
    if not project:
        return jsonify({'error': 'Invalid project name'}), 400
    path = get_project_path(project)
    if os.path.exists(path):
        return jsonify({'error': 'Project exists'}), 400
    try:
        os.makedirs(path, exist_ok=True)
        default_tex = f"""\\documentclass{{article}}
\\title{{{raw}}}
\\author{{OpenTex Editor}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle
\\section{{Intro}}
This is a new project: {project}
\\end{{document}}"""
        with open(os.path.join(path, 'document.tex'), 'w', encoding='utf-8') as f:
            f.write(default_tex)
        return jsonify({'message': 'created', 'project': project}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ----------------- Upload ZIP as project -----------------
@app.route('/api/upload_zip', methods=['POST'])
def upload_zip():
    if 'project_zip' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    f = request.files['project_zip']
    if not f or f.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not f.filename.endswith('.zip'):
        return jsonify({'error': 'Invalid file type, upload .zip'}), 400
    project = sanitize_name(os.path.splitext(f.filename)[0])
    if not project:
        return jsonify({'error': 'Invalid zip filename'}), 400
    ppath = get_project_path(project)
    if os.path.exists(ppath):
        return jsonify({'error': 'Project already exists'}), 400
    os.makedirs(ppath, exist_ok=True)
    try:
        data = io.BytesIO(f.read())
        with zipfile.ZipFile(data, 'r') as z:
            for member in z.infolist():
                if member.is_dir():
                    continue
                base = os.path.basename(member.filename)
                safe = sanitize_name(base)
                if not safe:
                    continue
                tgt = os.path.join(ppath, safe)
                if os.path.commonpath([ppath, tgt]) != ppath:
                    continue
                with open(tgt, 'wb') as out:
                    out.write(z.read(member.filename))
        return jsonify({'message': 'uploaded', 'project': project}), 201
    except Exception as e:
        if os.path.exists(ppath):
            shutil.rmtree(ppath)
        return jsonify({'error': str(e)}), 500

# ----------------- Project-level: list files / delete (DELETE or POST fallback) -----------------
@app.route('/api/projects/<project_name>', methods=['GET', 'DELETE', 'POST'])
def project_get_or_delete(project_name):
    ppath = get_project_path(project_name)
    if request.method == 'GET':
        if not ppath or not os.path.isdir(ppath):
            return jsonify({'error': 'Project not found'}), 404
        files = []
        for ent in os.scandir(ppath):
            if ent.is_file():
                files.insert(0, ent.name) if ent.name.endswith('.tex') else files.append(ent.name)
        return jsonify(files)

    # allow deletion via DELETE or POST (POST is fallback)
    if request.method in ('DELETE', 'POST'):
        if not ppath or not os.path.isdir(ppath):
            return jsonify({'error': 'Project not found'}), 404
        try:
            shutil.rmtree(ppath)
            return jsonify({'message': 'deleted', 'project': project_name})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

# explicit POST-only delete fallback endpoint
@app.route('/api/projects/<project_name>/delete', methods=['POST'])
def project_delete_via_post(project_name):
    ppath = get_project_path(project_name)
    if not ppath or not os.path.isdir(ppath):
        return jsonify({'error': 'Project not found'}), 404
    try:
        shutil.rmtree(ppath)
        return jsonify({'message': 'deleted', 'project': project_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ----------------- Project files: list / create / delete -----------------
@app.route('/api/projects/<project_name>/files', methods=['GET', 'POST', 'DELETE'])
def project_files_create_delete(project_name):
    ppath = get_project_path(project_name)
    if not ppath or not os.path.isdir(ppath):
        return jsonify({'error': 'Project not found'}), 404

    if request.method == 'GET':
        files = []
        for ent in os.scandir(ppath):
            if ent.is_file():
                files.insert(0, ent.name) if ent.name.endswith('.tex') else files.append(ent.name)
        return jsonify(files)

    if request.method == 'POST':
        data = request.json or {}
        raw = data.get('name')
        if not raw:
            return jsonify({'error': 'File name required'}), 400
        fname = sanitize_name(raw)
        if not fname:
            return jsonify({'error': 'Invalid file name'}), 400
        fpath = os.path.join(ppath, fname)
        if os.path.exists(fpath):
            return jsonify({'error': 'File exists'}), 400
        try:
            content = data.get('content', '')
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(content)
            return jsonify({'message': 'created', 'file': fname}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    if request.method == 'DELETE':
        fname_raw = request.args.get('file')
        if not fname_raw:
            return jsonify({'error': 'file query required'}), 400
        fname = sanitize_name(fname_raw)
        if not fname:
            return jsonify({'error': 'Invalid file name'}), 400
        fpath = os.path.join(ppath, fname)
        if not os.path.exists(fpath):
            return jsonify({'error': 'File not found'}), 404
        try:
            os.remove(fpath)
            return jsonify({'message': 'deleted', 'file': fname})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

# ----------------- Get or save a specific file -----------------
@app.route('/api/projects/<project_name>/<file_name>', methods=['GET', 'POST'])
def file_get_or_save(project_name, file_name):
    if request.method == 'GET':
        fpath = get_file_path(project_name, file_name)
        if not fpath or not os.path.isfile(fpath):
            return jsonify({'error': 'File not found'}), 404
        return send_file(fpath, mimetype='text/plain')
    else:
        fpath = get_file_path(project_name, file_name)
        if not fpath:
            return jsonify({'error': 'Invalid file path'}), 400
        try:
            body = request.data.decode('utf-8')
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(body)
            return jsonify({'message': 'saved', 'file': file_name})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

# ----------------- Compile LaTeX -> return PDF -----------------
@app.route('/api/compile', methods=['POST'])
def compile_latex():
    data = request.get_json(silent=True) or {}
    project = data.get('project')
    main = data.get('file')
    if not project or not main:
        return jsonify({'error': 'project and file required'}), 400
    ppath = get_project_path(project)
    fpath = get_file_path(project, main)
    if not ppath or not fpath or not os.path.isfile(fpath):
        return jsonify({'error': 'Main file not found'}), 404
    pdf = get_pdf_path(project, main)
    command = ['pdflatex', '-interaction=nonstopmode', '-output-directory=.', main]
    try:
        subprocess.run(command, cwd=ppath, capture_output=True, text=True, timeout=30)
        # run twice to resolve references if produced
        if os.path.exists(pdf):
            subprocess.run(command, cwd=ppath, capture_output=True, text=True, timeout=30)
        if not os.path.exists(pdf):
            return jsonify({'error': 'PDF not generated'}), 400
        return send_file(pdf, mimetype='application/pdf', as_attachment=False)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download_pdf', methods=['GET'])
def download_pdf():
    project = request.args.get('project')
    file = request.args.get('file')
    pdf = get_pdf_path(project, file)
    if not pdf or not os.path.exists(pdf):
        return jsonify({'error': 'PDF not found. Please compile first.'}), 404
    return send_file(pdf, as_attachment=True, download_name=os.path.basename(pdf))

# ----------------- Git config & push (global key) -----------------
def save_git_config(host, username, private_key_pem, public_key_pem):
    os.makedirs(GIT_CONFIG_DIR, exist_ok=True)
    priv_path = os.path.join(GIT_CONFIG_DIR, 'id_rsa')
    pub_path = os.path.join(GIT_CONFIG_DIR, 'id_rsa.pub')
    cfg_path = os.path.join(GIT_CONFIG_DIR, 'config.json')

    with open(priv_path, 'wb') as f:
        f.write(private_key_pem.encode('utf-8'))
    os.chmod(priv_path, 0o600)

    if public_key_pem:
        with open(pub_path, 'wb') as f:
            f.write(public_key_pem.encode('utf-8'))

    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump({'host': host, 'username': username, 'private_key_path': priv_path, 'public_key_path': pub_path}, f)

    return {'host': host, 'username': username, 'private_key_path': priv_path, 'public_key_path': pub_path}

def load_git_config():
    cfg_path = os.path.join(GIT_CONFIG_DIR, 'config.json')
    if not os.path.exists(cfg_path):
        return None
    with open(cfg_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {'host': data.get('host'), 'username': data.get('username'), 'private_key_path': data.get('private_key_path'), 'public_key_path': data.get('public_key_path')}

def run_git_commands(project_path, git_cfg, project_name):
    result = {'ok': False, 'steps': []}
    if not git_cfg or not git_cfg.get('private_key_path'):
        result['steps'].append({'error': 'Git config / private key not set.'})
        return result

    priv_key_path = git_cfg['private_key_path']
    host = git_cfg.get('host')
    username = git_cfg.get('username')
    if not host or not username:
        result['steps'].append({'error': 'Git host/username not configured.'})
        return result

    repo_name = f"{project_name}-tex"
    remote_url = f"git@{host}:{username}/{repo_name}.git"
    ssh_cmd = f"ssh -i {priv_key_path} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

    env = os.environ.copy()
    env['GIT_SSH_COMMAND'] = ssh_cmd

    def run(cmd, cwd=None):
        try:
            proc = subprocess.run(cmd, cwd=cwd, shell=False, capture_output=True, text=True, env=env, timeout=60)
            return {'cmd': cmd, 'returncode': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr}
        except Exception as e:
            return {'cmd': cmd, 'returncode': 99, 'stdout': '', 'stderr': str(e)}

    # 1️⃣ Initialize repository and set default branch to main
    if not os.path.exists(os.path.join(project_path, '.git')):
        r = run(['git', 'init', '-b', 'main'], cwd=project_path)
        result['steps'].append(r)
        if r['returncode'] != 0:
            return result
    else:
        # ensure branch is main if re-init
        run(['git', 'branch', '-M', 'main'], cwd=project_path)

    # 2️⃣ Configure username and email for commits
    run(['git', 'config', 'user.name', username], cwd=project_path)
    run(['git', 'config', 'user.email', f'{username}@{host}'], cwd=project_path)

    # 3️⃣ Stage and commit everything
    r = run(['git', 'add', '.'], cwd=project_path)
    result['steps'].append(r)
    r = run(['git', 'commit', '-m', 'Auto commit from OpenTex Editor'], cwd=project_path)
    result['steps'].append(r)

    # 4️⃣ Configure remote
    run(['git', 'remote', 'remove', 'origin'], cwd=project_path)
    r = run(['git', 'remote', 'add', 'origin', remote_url], cwd=project_path)
    result['steps'].append(r)

    # 5️⃣ Push to main
    r = run(['git', 'push', '-u', 'origin', 'main'], cwd=project_path)
    result['steps'].append(r)
    if r['returncode'] == 0:
        result['ok'] = True
    return result


@app.route('/api/git/config', methods=['GET', 'POST'])
def api_git_config():
    if request.method == 'GET':
        cfg = load_git_config()
        if not cfg:
            return jsonify({'configured': False})
        return jsonify({'configured': True, 'host': cfg.get('host'), 'username': cfg.get('username')})
    # POST
    host = request.form.get('host')
    username = request.form.get('username')
    priv = request.files.get('private_key')
    pub = request.files.get('public_key')
    if not host or not username or not priv:
        return jsonify({'error': 'host, username and private_key required'}), 400
    try:
        pk = priv.read().decode('utf-8')
        pubk = pub.read().decode('utf-8') if pub else None
        cfg = save_git_config(host, username, pk, pubk)
        return jsonify({'message': 'git config saved', 'host': cfg['host'], 'username': cfg['username']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_name>/git_push', methods=['POST'])
def api_git_push(project_name):
    ppath = get_project_path(project_name)
    if not ppath or not os.path.isdir(ppath):
        return jsonify({'error': 'Project not found'}), 404
    cfg = load_git_config()
    if not cfg:
        return jsonify({'error': 'Git not configured'}), 400
    result = run_git_commands(ppath, cfg, project_name)
    return jsonify(result)

# ----------------- Error handlers (JSON) -----------------
@app.errorhandler(405)
def handle_405(e):
    return jsonify({'error': 'Method Not Allowed', 'description': str(e)}), 405

@app.errorhandler(500)
def handle_500(e):
    if isinstance(e, HTTPException):
        return jsonify({'error': e.name, 'description': e.description}), e.code
    return jsonify({'error': 'Internal Server Error', 'description': str(e)}), 500

# ----------------- Run if executed directly -----------------
if __name__ == '__main__':
    # development server (not used in container typically)
    app.run(host='0.0.0.0', port=5000, debug=True)
