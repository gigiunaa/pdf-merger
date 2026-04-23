from flask import Flask, request, jsonify
import requests
from pypdf import PdfMerger
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
from io import BytesIO
import os
import tempfile
import logging

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
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code == 204:
        return None
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0]["id"] if data else None


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


def download_pdf(url, headers=None):
    r = requests.get(url, headers=headers, stream=True, timeout=60)
    r.raise_for_status()
    temp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
    for chunk in r.iter_content(chunk_size=8192):
        temp.write(chunk)
    temp.close()
    return temp.name


def merge_pdfs(pdf_files):
    merger = PdfMerger()
    for pdf in pdf_files:
        merger.append(pdf)
    output = BytesIO()
    merger.write(output)
    merger.close()
    output.seek(0)
    return output


def upload_to_workdrive(access_token, pdf_bytes, filename):
    url = f"{WORKDRIVE_BASE}/upload"
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    files = {"content": (filename, pdf_bytes, "application/pdf")}
    data = {"parent_id": WORKDRIVE_FOLDER_ID, "filename": filename, "override-name-exist": "true"}
    r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
    r.raise_for_status()
    return r.json()


def attach_to_candidate(access_token, candidate_id, pdf_bytes, filename):
    url = f"{RECRUIT_BASE}/Candidates/{candidate_id}/Attachments"
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    files = {"file": (filename, pdf_bytes, "application/pdf")}
    params = {"attachments_category": "Others"}
    r = requests.post(url, headers=headers, files=files, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


@app.route('/')
def home():
    return jsonify({"status": "Onboarding PDF API is running"})


@app.route('/process-onboarding', methods=['POST'])
def process_onboarding():
    try:
        data = request.get_json()
        logger.info(f"Received request for: {data.get('email')}")
        
        email = data.get('email')
        id_file_url = data.get('id_file_url')
        bank_file_url = data.get('bank_file_url')
        
        if not email:
            return jsonify({"error": "email is required"}), 400
        
        access_token = get_access_token()
        logger.info("Got access token")
        
        candidate_id = find_candidate_by_email(access_token, email)
        if not candidate_id:
            return jsonify({"error": f"Candidate not found: {email}"}), 404
        logger.info(f"Found candidate: {candidate_id}")
        
        onboarding_pdf = generate_onboarding_pdf(data)
        temp_onboarding = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_onboarding.write(onboarding_pdf.getvalue())
        temp_onboarding.close()
        
        pdfs_to_merge = [temp_onboarding.name]
        temp_files = [temp_onboarding.name]
        
        if id_file_url:
            id_pdf = download_pdf(id_file_url)
            pdfs_to_merge.append(id_pdf)
            temp_files.append(id_pdf)
            logger.info("Downloaded ID file")
        
        if bank_file_url:
            bank_pdf = download_pdf(bank_file_url)
            pdfs_to_merge.append(bank_pdf)
            temp_files.append(bank_pdf)
            logger.info("Downloaded Bank file")
        
        merged = merge_pdfs(pdfs_to_merge)
        logger.info("PDFs merged")
        
        first = data.get('first_name', '')
        last = data.get('last_name', '')
        filename = f"Onboarding - {first} {last}.pdf"
        
        merged_bytes = merged.getvalue()
        
        wd_result = upload_to_workdrive(access_token, merged_bytes, filename)
        logger.info("Uploaded to WorkDrive")
        
        attach_result = attach_to_candidate(access_token, candidate_id, merged_bytes, filename)
        logger.info("Attached to candidate")
        
        for tf in temp_files:
            try:
                os.unlink(tf)
            except:
                pass
        
        return jsonify({
            "status": "success",
            "candidate_id": candidate_id,
            "filename": filename,
            "workdrive": "uploaded",
            "recruit_attachment": "uploaded"
        })
    
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error: {e.response.text if e.response else str(e)}")
        return jsonify({"error": str(e), "details": e.response.text if e.response else None}), 500
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
