#!/usr/bin/env python3
"""
PDF Chapter Splitter - Local Web Application
Runs entirely offline on localhost
Supports nested bookmarks and ZIP downloads
"""

from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import os
import shutil
from pdf_processor import PDFChapterSplitter
from io import BytesIO
import zipfile

# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size
app.secret_key = 'your-secret-key-here'

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf'}

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

def allowed_file(filename):
    """Check if uploaded file has valid PDF extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    """Render main upload page"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """
    Handle PDF upload and chapter detection
    Returns JSON with detected chapters
    """
    # Validate file upload
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Only PDF files are allowed'}), 400
    
    try:
        # Save uploaded file securely
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Initialize PDF processor
        splitter = PDFChapterSplitter(filepath)
        
        # Detect chapters using bookmarks or heading analysis
        chapters = splitter.detect_chapters()
        
        # Store filepath in session for later splitting
        return jsonify({
            'success': True,
            'filename': filename,
            'chapters': chapters,
            'detection_method': splitter.detection_method
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/split', methods=['POST'])
def split_pdf():
    """
    Split PDF into chapters based on detected structure
    Returns list of generated files
    """
    try:
        data = request.get_json()
        filename = secure_filename(data['filename'])
        chapters = data['chapters']
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        output_dir = os.path.join(app.config['OUTPUT_FOLDER'], 
                                 filename.rsplit('.', 1)[0])
        
        # Create output directory for this PDF
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize splitter and perform split
        splitter = PDFChapterSplitter(filepath)
        output_files = splitter.split_chapters(chapters, output_dir)
        
        return jsonify({
            'success': True,
            'files': output_files,
            'output_dir': output_dir
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<path:filename>')
def download_file(filename):
    """Download individual chapter file"""
    try:
        file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@app.route('/download-all/<path:dirname>')
def download_all(dirname):
    """
    Download all chapters as a single ZIP file
    Creates zip in memory for efficient streaming
    """
    try:
        output_dir = os.path.join(app.config['OUTPUT_FOLDER'], dirname)
        
        # Verify directory exists
        if not os.path.exists(output_dir):
            return jsonify({'error': 'Output directory not found'}), 404
        
        # Create zip file in memory
        memory_file = BytesIO()
        
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add all PDF files from the output directory
            pdf_count = 0
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    if file.endswith('.pdf'):
                        file_path = os.path.join(root, file)
                        # Add file to zip with just the filename (no directory structure)
                        arcname = os.path.basename(file)
                        zf.write(file_path, arcname)
                        pdf_count += 1
            
            # If no PDFs found, return error
            if pdf_count == 0:
                return jsonify({'error': 'No PDF files found to zip'}), 404
        
        # Reset file pointer to beginning
        memory_file.seek(0)
        
        # Generate zip filename from directory name
        zip_filename = f"{dirname}_all_chapters.zip"
        
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )
    
    except Exception as e:
        print(f"Error creating zip: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Clean up uploaded and output files"""
    try:
        # Clear uploads and output directories
        for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER']]:
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 PDF Chapter Splitter running at http://localhost:5000")
    print("📁 Uploads saved to:", os.path.abspath(app.config['UPLOAD_FOLDER']))
    print("📄 Output saved to:", os.path.abspath(app.config['OUTPUT_FOLDER']))
    print("💡 Features: Nested bookmarks, ZIP download, readable filenames")
    port = int(os.environ.get('PORT', 5000))
app.run(debug=False, host='0.0.0.0', port=port)

