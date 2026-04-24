from flask import Flask, request, jsonify
import requests
from pypdf import PdfMerger
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
from PIL import Image
from io import BytesIO
import os
import tempfile
import logging
import ast

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

CLIENT_ID = os.environ.get('ZOHO_CLIENT_ID')
CLIENT_SECRET = os.environ.get('ZOHO_CLIENT_SECRET')
REFRESH_TOKEN = os.environ.get('ZOHO_REFRESH_TOKEN')
WORKDRIVE_FOLDER_ID = os.environ.get('WORKDRIVE_FOLDER_ID')

ZOHO_DOMAIN = "com"
RECRUIT_BASE = f"https://recruit.zoho.{ZOHO_DOMAIN}/recruit/v2"
WORKDRIVE_BASE = f"https://www.zohoapis.{ZOHO_DOMAIN}/workdrive/api/v1"


def get_access_token():
    url = f"https://accounts.zoho.{ZOHO_DOMAIN}/oauth/v2/token"
    data = {
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token"
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def find_candidate_by_email(access_token, email):
    url = f"{RECRUIT_BASE}/Candidates/search"
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    params = {"criteria": f"(Email:equals:{email})"}
    logger.info(f"Searching candidate: {email}")
    r = requests.get(url, headers=headers, params=params, timeout=30)
    logger.info(f"Search status: {r.status_code}")
    if r.status_code == 204:
        return None
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0]["id"] if data else None


def extract_url(val):
    if val is None:
        return None
    if isinstance(val, list):
        return val[0] if val else None
    if isinstance(val, str):
        s = val.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, list) and parsed:
                    return parsed[0]
            except:
                pass
        return s
    return None


def generate_onboarding_pdf(form_data):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.7*inch, bottomMargin=0.7*inch)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, alignment=1, spaceAfter=20)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=14, spaceAfter=10, spaceBefore=15)
    label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=11, spaceAfter=6)
    
    story = []
    story.append(Paragraph("CANDIDATE ONBOARDING SUMMARY", title_style))
    story.append(Paragraph(f"<b>Submission Date:</b> {form_data.get('submission_date', '')}", label_style))
    story.append(Spacer(1, 0.2*inch))
    
    story.append(Paragraph("PERSONAL INFORMATION", section_style))
    story.append(Paragraph(f"<b>Full Name:</b> {form_data.get('first_name', '')} {form_data.get('last_name', '')}", label_style))
    story.append(Paragraph(f"<b>Email:</b> {form_data.get('email', '')}", label_style))
    story.append(Paragraph(f"<b>Phone Number:</b> {form_data.get('phone', '')}", label_style))
    story.append(Paragraph(f"<b>Current Living Address:</b> {form_data.get('address', '')}", label_style))
    
    story.append(Paragraph("EMERGENCY CONTACT", section_style))
    story.append(Paragraph(f"<b>Name:</b> {form_data.get('emergency_name', '')}", label_style))
    story.append(Paragraph(f"<b>Phone:</b> {form_data.get('emergency_phone', '')}", label_style))
    
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("<i>Supporting documents (ID and Bank Requisites) are attached on the following pages.</i>", label_style))
    
    doc.build(story)
    buffer.seek(0)
    return buffer


def download_file_as_pdf(url, access_token=None):
    headers = {}
    if access_token:
        headers["Authorization"] = f"Zoho-oauthtoken {access_token}"
    
    logger.info(f"Downloading: {url[:100]}")
    r = requests.get(url, headers=headers, stream=True, timeout=60, allow_redirects=True)
    logger.info(f"Download status: {r.status_code}, Content-Type: {r.headers.get('Content-Type')}")
    r.raise_for_status()
    
    content_type = r.headers.get('Content-Type', '').lower()
    url_lower = url.lower().split('?')[0]
    
    temp_raw = tempfile.NamedTemporaryFile(delete=False)
    for chunk in r.iter_content(chunk_size=8192):
        temp_raw.write(chunk)
    temp_raw.close()
    
    is_pdf = 'pdf' in content_type or url_lower.endswith('.pdf')
    
    if is_pdf:
        return temp_raw.name
    
    is_image = (
        any(ext in content_type for ext in ['image/', 'png', 'jpeg', 'jpg', 'webp'])
        or any(url_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif'])
    )
    
    if is_image:
        logger.info("Converting image to PDF")
        img = Image.open(temp_raw.name)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        pdf_path = temp_raw.name + '.pdf'
        img.save(pdf_path, 'PDF', resolution=100.0)
        try:
            os.unlink(temp_raw.name)
        except:
            pass
        return pdf_path
    
    try:
        with open(temp_raw.name, 'rb') as f:
            header = f.read(4)
        logger.info(f"File header bytes: {header}")
        if header.startswith(b'%PDF'):
            return temp_raw.name
        if header[:2] in (b'\xff\xd8', b'\x89P') or header[:3] == b'GIF':
            img = Image.open(temp_raw.name)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            pdf_path = temp_raw.name + '.pdf'
            img.save(pdf_path, 'PDF', resolution=100.0)
            try:
                os.unlink(temp_raw.name)
            except:
                pass
            return pdf_path
    except Exception as e:
        logger.error(f"Magic byte detection failed: {e}")
    
    try:
        os.unlink(temp_raw.name)
    except:
        pass
    raise ValueError(f"Unsupported file type. Content-Type: {content_type}")


def merge_pdfs(pdf_files):
    merger = PdfMerger()
    for pdf in pdf_files:
        merger.append(pdf)
    output = BytesIO()
    merger.write(output)
    merger.close()
    output.seek(0)
    return output


def read_file_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def create_workdrive_folder(access_token, parent_id, folder_name):
    url = f"{WORKDRIVE_BASE}/files"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/vnd.api+json",
        "Accept": "application/vnd.api+json"
    }
    payload = {
        "data": {
            "attributes": {
                "name": folder_name,
                "parent_id": parent_id
            },
            "type": "files"
        }
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    logger.info(f"Create folder status: {r.status_code}")
    if r.status_code in (200, 201):
        data = r.json().get("data", {})
        folder_id = data.get("id")
        logger.info(f"Folder created: {folder_id}")
        return folder_id
    logger.error(f"Create folder failed: {r.text}")
    r.raise_for_status()


def upload_to_workdrive(access_token, pdf_bytes, filename, parent_folder_id):
    url = f"{WORKDRIVE_BASE}/upload"
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    files = {"content": (filename, pdf_bytes, "application/pdf")}
    data = {"parent_id": parent_folder_id, "filename": filename, "override-name-exist": "true"}
    r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
    logger.info(f"WorkDrive upload '{filename}' status: {r.status_code}")
    r.raise_for_status()
    return r.json()


def attach_to_candidate(access_token, candidate_id, pdf_bytes, filename):
    url = f"{RECRUIT_BASE}/Candidates/{candidate_id}/Attachments"
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    files = {"file": (filename, pdf_bytes, "application/pdf")}
    params = {"attachments_category": "Others"}
    r = requests.post(url, headers=headers, files=files, params=params, timeout=60)
    logger.info(f"Recruit attach '{filename}' status: {r.status_code}")
    r.raise_for_status()
    return r.json()


@app.route('/')
def home():
    return jsonify({"status": "Onboarding PDF API is running"})


@app.route('/process-onboarding', methods=['POST'])
def process_onboarding():
    temp_files = []
    try:
        data = request.get_json()
        logger.info(f"Received request for: {data.get('email')}")
        
        email = data.get('email')
        id_file_url = extract_url(data.get('id_file_url'))
        bank_file_url = extract_url(data.get('bank_file_url'))
        
        first = data.get('first_name', '').strip()
        last = data.get('last_name', '').strip()
        full_name = f"{first} {last}".strip()
        
        if not email:
            return jsonify({"error": "email is required"}), 400
        
        access_token = get_access_token()
        logger.info("Got access token")
        
        candidate_id = find_candidate_by_email(access_token, email)
        if not candidate_id:
            return jsonify({"error": f"Candidate not found: {email}"}), 404
        logger.info(f"Found candidate: {candidate_id}")
        
        # Generate onboarding summary PDF
        onboarding_pdf = generate_onboarding_pdf(data)
        temp_onboarding = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_onboarding.write(onboarding_pdf.getvalue())
        temp_onboarding.close()
        temp_files.append(temp_onboarding.name)
        logger.info("Generated onboarding PDF")
        
        # Download ID and Bank files
        id_pdf_path = None
        bank_pdf_path = None
        
        if id_file_url:
            id_pdf_path = download_file_as_pdf(id_file_url, access_token=access_token)
            temp_files.append(id_pdf_path)
            logger.info("Downloaded ID file")
        
        if bank_file_url:
            bank_pdf_path = download_file_as_pdf(bank_file_url, access_token=access_token)
            temp_files.append(bank_pdf_path)
            logger.info("Downloaded Bank file")
        
        # Create merged PDF (Summary + ID + Bank)
        pdfs_to_merge = [temp_onboarding.name]
        if id_pdf_path:
            pdfs_to_merge.append(id_pdf_path)
        if bank_pdf_path:
            pdfs_to_merge.append(bank_pdf_path)
        
        merged_pdf = merge_pdfs(pdfs_to_merge)
        merged_bytes = merged_pdf.getvalue()
        logger.info(f"Merged {len(pdfs_to_merge)} PDFs")
        
        # Prepare individual files
        full_filename = f"Onboarding - {full_name}.pdf"
        id_filename = f"ID - {full_name}.pdf"
        bank_filename = f"Bank Requisites - {full_name}.pdf"
        
        id_bytes = read_file_bytes(id_pdf_path) if id_pdf_path else None
        bank_bytes = read_file_bytes(bank_pdf_path) if bank_pdf_path else None
        
        # Create candidate folder in WorkDrive
        candidate_folder_id = create_workdrive_folder(access_token, WORKDRIVE_FOLDER_ID, full_name)
        logger.info(f"Created WorkDrive folder: {candidate_folder_id}")
        
        # Upload 3 files to WorkDrive candidate folder
        upload_to_workdrive(access_token, merged_bytes, full_filename, candidate_folder_id)
        if id_bytes:
            upload_to_workdrive(access_token, id_bytes, id_filename, candidate_folder_id)
        if bank_bytes:
            upload_to_workdrive(access_token, bank_bytes, bank_filename, candidate_folder_id)
        logger.info("Uploaded 3 files to WorkDrive")
        
        # Attach 3 files to Recruit candidate
        attach_to_candidate(access_token, candidate_id, merged_bytes, full_filename)
        if id_bytes:
            attach_to_candidate(access_token, candidate_id, id_bytes, id_filename)
        if bank_bytes:
            attach_to_candidate(access_token, candidate_id, bank_bytes, bank_filename)
        logger.info("Attached 3 files to candidate")
        
        return jsonify({
            "status": "success",
            "candidate_id": candidate_id,
            "workdrive_folder_id": candidate_folder_id,
            "files": [full_filename, id_filename, bank_filename]
        })
    
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error: {e.response.text if e.response else str(e)}")
        return jsonify({"error": str(e), "details": e.response.text if e.response else None}), 500
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        for tf in temp_files:
            try:
                os.unlink(tf)
            except:
                pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
