import os

def generate_tree(startpath, exclude_dirs, exclude_files, exclude_exts):
    """
    Generates a visual tree structure of the project.
    """
    tree_str = "PROJECT STRUCTURE:\n"
    tree_str += f"{os.path.basename(os.path.abspath(startpath))}/\n"
    
    for root, dirs, files in os.walk(startpath):
        # Filter directories in-place
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        
        level = root.replace(startpath, '').count(os.sep)
        indent = ' ' * 4 * level
        sub_indent = ' ' * 4 * (level + 1)
        
        if level > 0:
            tree_str += f"{indent}{os.path.basename(root)}/\n"
        
        for f in sorted(files):
            file_ext = os.path.splitext(f)[1].lower()
            if f not in exclude_files and file_ext not in exclude_exts:
                tree_str += f"{sub_indent}{f}\n"
    return tree_str

def merge_project_files(output_filename="full_Nerkhban_project_code.txt"):
    # Configuration
    EXCLUDE_DIRS = {
        'node_modules', '.git', '.idea', '__pycache__', 
        'venv', 'env', '.vscode', 'dist', 'build', '.terraform', 'vendor', '.venv'
    }
    
    EXCLUDE_EXTENSIONS = {
        '.png', '.jpg', '.jpeg', '.gif', '.ico', 
        '.pyc', '.exe', '.dll', '.so', '.sqlite', '.db', 
        '.lock', '.pdf', '.docx'
    }

    EXCLUDE_FILES = {
        output_filename, 
        'package-lock.json',
        'yarn.lock',
        'code_dumper.py',
        '.DS_Store'
    }

    print(f"Generating project tree and merging files into {output_filename}...")

    with open(output_filename, 'w', encoding='utf-8') as outfile:
        # 1. Write the Tree Structure first
        project_tree = generate_tree(".", EXCLUDE_DIRS, EXCLUDE_FILES, EXCLUDE_EXTENSIONS)
        outfile.write(project_tree)
        outfile.write(f"\n{'#'*60}\n")
        outfile.write(f"{'#'*15} FILE CONTENTS START BELOW {'#'*15}\n")
        outfile.write(f"{'#'*60}\n\n")

        # 2. Walk through the directory tree for contents
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in sorted(files):
                file_ext = os.path.splitext(file)[1].lower()
                
                if (file in EXCLUDE_FILES or file_ext in EXCLUDE_EXTENSIONS):
                    continue

                file_path = os.path.join(root, file)

                try:
                    # Write file header for clarity
                    outfile.write(f"\n{'='*50}\n")
                    outfile.write(f"FILE: {file_path}\n")
                    outfile.write(f"{'='*50}\n\n")

                    # Read and write content
                    with open(file_path, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                        outfile.write("\n")
                    
                    print(f"Added: {file_path}")

                except Exception as e:
                    print(f"Skipping {file_path}: {e}")

    print(f"\nDone! Project overview and code are in {output_filename}")

if __name__ == "__main__":
    merge_project_files()