# OpenTex 

This is a self-hosted, Docker-based LaTeX editor designed to run on a Raspberry Pi.

This version supports:

- A "Home Page" / Dashboard to view and manage all projects.

- A separate Editor page for writing and compiling.

- Persistent Projects: Your work is saved in the projects directory.

- AMOLED Dark Theme as the one and only theme.

- Project Upload: You can upload existing projects as .zip files.

- Keybindings: Ctrl+S (or Cmd+S) to Save, and Ctrl+Enter (or Cmd+Enter) to Compile.

- PDF Download: A dedicated button to download your compiled PDF.

- Production Server: Uses gunicorn for a robust, multi-worker web server.

## Project File Structure

Here is the file structure for this repository. The projects/ directory is created by you and is where your work is stored, separate from the application code.

OpenTex/
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── app.py
├── dashboard.html
├── editor.html
└── projects/
    └── (Your projects will be saved here)


## How to Run

Prerequisite: You must have Docker and docker-compose installed on your Raspberry Pi.

Create Project Directory:
Before you start, you must create a directory to store your projects. This is where your .tex files will live.

```mkdir projects```


Build and Run:
From this directory (which contains all the files: docker-compose.yml, Dockerfile, etc.), run:


```docker-compose up --build -d```


(Added -d to run it in detached mode, so it runs in the background)

Access Your Editor:
Once the build is complete, open your web browser and go to your Pi's IP address:

```http://<your-raspberry-pi-ip-address>:8080```

This will show the Dashboard.

Clicking a project (or creating a new one) will take you to the Editor page (e.g., http://...:8080/editor?project=my_project).