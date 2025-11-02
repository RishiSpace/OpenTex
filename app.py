from flask import Flask, request, send_from_directory, jsonify, send_file
import subprocess
import os
import re
import shutil
import zipfile
import io

app = Flask(__name__)

# Define the base directory for projects
PROJECTS_DIR = os.path.join(app.root_path, 'projects')

# --- Helper Functions ---

def sanitize_name(name):
    """Sanitizes a project or file name."""
    name = str(name).strip()
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'[^a-zA-Z0-9_.-]', '', name)
    # Disallow names that could be path traversal
    if '..' in name or name.startswith(('/', '.')):
        return None
    return name

def get_project_path(project_name):
    """Gets the safe path for a project."""
    safe_project = sanitize_name(project_name)
    if not safe_project:
        return None
    return os.path.join(PROJECTS_DIR, safe_project)

def get_file_path(project_name, file_name):
    """Gets the safe path for a file within a project."""
    project_path = get_project_path(project_name)
    safe_file = sanitize_name(file_name)
    if not project_path or not safe_file:
        return None
    return os.path.join(project_path, safe_file)

def get_pdf_path(project_name, file_name):
    """Gets the safe path for a compiled PDF."""
    file_path = get_file_path(project_name, file_name)
    if not file_path:
        return None
    pdf_name = os.path.splitext(os.path.basename(file_path))[0] + '.pdf'
    return os.path.join(os.path.dirname(file_path), pdf_name)

# Ensure the projects directory exists when the app starts
if not os.path.exists(PROJECTS_DIR):
    os.makedirs(PROJECTS_DIR)

# --- HTML Page Routes ---

@app.route('/')
def dashboard():
    """Serves the main dashboard page."""
    return send_from_directory('.', 'dashboard.html')

@app.route('/editor')
def editor():
    """Serves the editor page."""
    return send_from_directory('.', 'editor.html')

# --- API Routes ---

@app.route('/api/projects', methods=['GET'])
def get_projects():
    """Lists all projects (directories) in PROJECTS_DIR."""
    projects = []
    if not os.path.exists(PROJECTS_DIR):
        os.makedirs(PROJECTS_DIR)
    for entry in os.scandir(PROJECTS_DIR):
        if entry.is_dir():
            projects.append(entry.name)
    return jsonify(projects)

@app.route('/api/projects', methods=['POST'])
def create_project():
    """Creates a new project directory with a default .tex file."""
    data = request.json
    project_name_raw = data.get('name')
    if not project_name_raw:
        return jsonify({"error": "Project name is required"}), 400
    
    project_name = sanitize_name(project_name_raw)
    if not project_name:
        return jsonify({"error": "Invalid project name"}), 400
    
    project_path = get_project_path(project_name)
    
    if os.path.exists(project_path):
        return jsonify({"error": "Project already exists"}), 400
    
    try:
        os.makedirs(project_path)
        default_tex_content = f"""
\\documentclass{{article}}
\\usepackage[english, bidi=basic, provide=*]{{babel}}
\\usepackage{{fontspec}}
\\babelfont{{rm}}{{Noto Sans}}
\\title{{{project_name_raw}}}
\\author{{OpenTex Editor}}
\\date{{\\today}}

\\begin{{document}}

\\maketitle

\\section{{Introduction}}
This is a new document in the '{project_name}' project.

$$ E = mc^2 $$

\\end{{document}}
"""
        with open(os.path.join(project_path, 'document.tex'), 'w') as f:
            f.write(default_tex_content)
        
        return jsonify({"message": f"Project '{project_name}' created.", "project_name": project_name}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/upload_zip', methods=['POST'])
def upload_zip():
    """Uploads a .zip file and extracts it as a new project."""
    if 'project_zip' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['project_zip']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file and file.filename.endswith('.zip'):
        # Sanitize the project name from the zip file name
        project_name = sanitize_name(os.path.splitext(file.filename)[0])
        if not project_name:
            return jsonify({"error": "Invalid zip file name"}), 400
        
        project_path = get_project_path(project_name)
        if os.path.exists(project_path):
            return jsonify({"error": f"Project '{project_name}' already exists"}), 400
        
        os.makedirs(project_path)

        try:
            # Read file into memory
            zip_data = io.BytesIO(file.read())
            with zipfile.ZipFile(zip_data, 'r') as zip_ref:
                # Securely extract files one by one
                for member in zip_ref.infolist():
                    # use member.filename (ZipInfo uses .filename)
                    if member.is_dir():
                        continue
                    # take basename to avoid directories inside zip
                    base_name = os.path.basename(member.filename)
                    member_name = sanitize_name(base_name)
                    if not member_name:
                        # Skip files with invalid names
                        print(f"Skipped invalid name: {member.filename}")
                        continue
                    target_path = os.path.join(project_path, member_name)
                    # Ensure the target is still within the project path
                    if os.path.commonpath([project_path, target_path]) != project_path:
                        print(f"Skipped potentially malicious file: {member.filename}")
                        continue
                    with open(target_path, "wb") as f:
                        f.write(zip_ref.read(member.filename))
            
            return jsonify({"message": f"Project '{project_name}' uploaded.", "project_name": project_name}), 201
        
        except Exception as e:
            # Clean up partial extraction on error
            if os.path.exists(project_path):
                shutil.rmtree(project_path)
            return jsonify({"error": f"Failed to extract zip: {str(e)}"}), 500
    
    return jsonify({"error": "Invalid file type, please upload a .zip"}), 400


@app.route('/api/projects/<project_name>', methods=['GET'])
def get_project_files(project_name):
    """Lists all files in a specific project."""
    project_path = get_project_path(project_name)
    if not project_path or not os.path.isdir(project_path):
        return jsonify({"error": "Project not found"}), 404
        
    files = []
    for entry in os.scandir(project_path):
        if entry.is_file():
            # Show .tex files first, then other files
            if entry.name.endswith('.tex'):
                files.insert(0, entry.name)
            else:
                files.append(entry.name)
    return jsonify(files)

@app.route('/api/projects/<project_name>/<file_name>', methods=['GET'])
def get_file_content(project_name, file_name):
    """Gets the text content of a specific file."""
    file_path = get_file_path(project_name, file_name)
    if not file_path or not os.path.isfile(file_path):
        return jsonify({"error": "File not found"}), 404
    
    return send_file(file_path, mimetype='text/plain')

@app.route('/api/projects/<project_name>/<file_name>', methods=['POST'])
def save_file_content(project_name, file_name):
    """Saves text content to a specific file."""
    file_path = get_file_path(project_name, file_name)
    if not file_path:
        return jsonify({"error": "Invalid file path"}), 400
    
    try:
        code = request.data.decode('utf-8')
        with open(file_path, 'w') as f:
            f.write(code)
        return jsonify({"message": f"File '{file_name}' saved."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# New endpoint: create file in a project
@app.route('/api/projects/<project_name>/files', methods=['POST'])
def create_file(project_name):
    """
    Create a new file in the project.
    Expects JSON: { "name": "filename.tex", "content": "optional initial content" }
    """
    project_path = get_project_path(project_name)
    if not project_path or not os.path.isdir(project_path):
        return jsonify({"error": "Project not found"}), 404

    data = request.json or {}
    file_name_raw = data.get('name')
    if not file_name_raw:
        return jsonify({"error": "File name is required"}), 400

    file_name = sanitize_name(file_name_raw)
    if not file_name:
        return jsonify({"error": "Invalid file name"}), 400

    file_path = os.path.join(project_path, file_name)
    if os.path.exists(file_path):
        return jsonify({"error": "File already exists"}), 400

    content = data.get('content', '')
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"message": f"File '{file_name}' created.", "file": file_name}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# New endpoint: delete file in a project
@app.route('/api/projects/<project_name>/files', methods=['DELETE'])
def delete_file(project_name):
    """
    Delete a file in the project.
    Query param: ?file=filename.ext
    """
    project_path = get_project_path(project_name)
    if not project_path or not os.path.isdir(project_path):
        return jsonify({"error": "Project not found"}), 404

    file_name_raw = request.args.get('file')
    if not file_name_raw:
        return jsonify({"error": "File query parameter required"}), 400

    file_name = sanitize_name(file_name_raw)
    if not file_name:
        return jsonify({"error": "Invalid file name"}), 400

    file_path = os.path.join(project_path, file_name)
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return jsonify({"error": "File not found"}), 404

    try:
        os.remove(file_path)
        return jsonify({"message": f"File '{file_name}' deleted."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/compile', methods=['POST'])
def compile_latex():
    """
    Compiles a .tex file within its project directory.
    """
    data = request.json
    project_name = data.get('project')
    main_file = data.get('file')

    if not project_name or not main_file:
        return jsonify({"error": "Project and main file are required"}), 400

    project_path = get_project_path(project_name)
    file_path = get_file_path(project_name, main_file)

    if not project_path or not file_path or not os.path.isfile(file_path):
        return jsonify({"error": "Main file not found"}), 404
    
    pdf_path = get_pdf_path(project_name, main_file)
    log_path = os.path.splitext(pdf_path)[0] + '.log'

    command = [
        'pdflatex',
        '-interaction=nonstopmode',
        '-output-directory=.', # Output to current dir
        main_file
    ]
    
    try:
        # Run 1
        proc = subprocess.run(command, cwd=project_path, capture_output=True, text=True, timeout=15)
        
        # Run 2 (only if first one produced a PDF)
        if os.path.exists(pdf_path):
             subprocess.run(command, cwd=project_path, capture_output=True, text=True, timeout=15)

        if not os.path.exists(pdf_path):
            error_log = "Compilation failed. PDF not generated."
            if os.path.exists(log_path):
                with open(log_path, 'r') as log:
                    error_log = log.read()
            return jsonify({"error": error_log}), 400

        # If successful, send the PDF file back for inline viewing
        return send_file(
            pdf_path,
            mimetype='application/pdf',
            as_attachment=False
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download_pdf', methods=['GET'])
def download_pdf():
    """Sends the compiled PDF as an attachment for download."""
    project_name = request.args.get('project')
    file_name = request.args.get('file')

    pdf_path = get_pdf_path(project_name, file_name)
    
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "PDF not found. Please compile first."}), 404
    
    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=os.path.basename(pdf_path)
    )

# Note: Gunicorn will be the entry point and will load the 'app' object.
