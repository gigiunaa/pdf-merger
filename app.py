from flask import Flask, request, send_file, jsonify
import requests
from pypdf import PdfMerger
from io import BytesIO
import os
import tempfile

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "PDF Merger API is running"})

@app.route('/merge', methods=['POST'])
def merge_pdfs():
    try:
        data = request.get_json()
        urls = data.get('urls', [])
        
        if not urls or len(urls) < 2:
            return jsonify({"error": "At least 2 URLs required"}), 400
        
        merger = PdfMerger()
        temp_files = []
        
        for idx, url in enumerate(urls):
            response = requests.get(url, stream=True, timeout=30)
            if response.status_code != 200:
                return jsonify({"error": f"Failed to download URL {idx}: {url}"}), 400
            
            temp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            for chunk in response.iter_content(chunk_size=8192):
                temp.write(chunk)
            temp.close()
            temp_files.append(temp.name)
            merger.append(temp.name)
        
        output = BytesIO()
        merger.write(output)
        merger.close()
        output.seek(0)
        
        for tf in temp_files:
            try:
                os.unlink(tf)
            except:
                pass
        
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='merged.pdf'
        )
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)