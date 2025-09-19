from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn
import re
import uuid
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('audit.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="GetGSA Coding Test API", description="Document ingestion and validation service")

# Setup templates
templates = Jinja2Templates(directory="templates")

# NAICS to SIN mapping
NAICS_SIN_MAPPING = {
    "541511": "54151S",
    "541512": "54151S", 
    "541611": "541611",
    "518210": "518210C"
}

class IngestRequest(BaseModel):
    company_profile: str
    past_performance: str

class CompanyProfile(BaseModel):
    company_name: Optional[str] = None
    uei: Optional[str] = None
    duns: Optional[str] = None
    naics: List[str] = []
    poc_name: Optional[str] = None
    poc_email: Optional[str] = None
    poc_phone: Optional[str] = None
    address: Optional[str] = None
    sam_registered: Optional[bool] = None

class PastPerformance(BaseModel):
    customer: Optional[str] = None
    contract: Optional[str] = None
    value: Optional[str] = None
    period: Optional[str] = None
    contact: Optional[str] = None

def parse_company_profile(text: str) -> CompanyProfile:
    """Parse company profile text into structured data"""
    profile = CompanyProfile()
    
    # Extract company name (first line)
    lines = text.strip().split('\n')
    if lines:
        profile.company_name = lines[0].strip()
    
    # Extract UEI
    uei_match = re.search(r'UEI:\s*([A-Z0-9]+)', text, re.IGNORECASE)
    if uei_match:
        profile.uei = uei_match.group(1)
    
    # Extract DUNS
    duns_match = re.search(r'DUNS:\s*(\d+)', text, re.IGNORECASE)
    if duns_match:
        profile.duns = duns_match.group(1)
    
    # Extract NAICS codes
    naics_match = re.search(r'NAICS:\s*([\d,\s]+)', text, re.IGNORECASE)
    if naics_match:
        naics_str = naics_match.group(1)
        profile.naics = [code.strip() for code in naics_str.split(',') if code.strip()]
    
    # Extract POC information
    poc_match = re.search(r'POC:\s*([^,]+),\s*([^,]+),\s*(.+)', text, re.IGNORECASE)
    if poc_match:
        profile.poc_name = poc_match.group(1).strip()
        profile.poc_email = poc_match.group(2).strip()
        profile.poc_phone = poc_match.group(3).strip()
    
    # Extract address
    address_match = re.search(r'Address:\s*(.+)', text, re.IGNORECASE)
    if address_match:
        profile.address = address_match.group(1).strip()
    
    # Extract SAM registration status
    sam_match = re.search(r'SAM\.gov:\s*(\w+)', text, re.IGNORECASE)
    if sam_match:
        profile.sam_registered = sam_match.group(1).lower() == 'registered'
    
    return profile

def parse_past_performance(text: str) -> PastPerformance:
    """Parse past performance text into structured data"""
    performance = PastPerformance()
    
    # Extract customer
    customer_match = re.search(r'Customer:\s*(.+)', text, re.IGNORECASE)
    if customer_match:
        performance.customer = customer_match.group(1).strip()
    
    # Extract contract
    contract_match = re.search(r'Contract:\s*(.+)', text, re.IGNORECASE)
    if contract_match:
        performance.contract = contract_match.group(1).strip()
    
    # Extract value
    value_match = re.search(r'Value:\s*(.+)', text, re.IGNORECASE)
    if value_match:
        performance.value = value_match.group(1).strip()
    
    # Extract period
    period_match = re.search(r'Period:\s*(.+)', text, re.IGNORECASE)
    if period_match:
        performance.period = period_match.group(1).strip()
    
    # Extract contact
    contact_match = re.search(r'Contact:\s*(.+)', text, re.IGNORECASE)
    if contact_match:
        performance.contact = contact_match.group(1).strip()
    
    return performance

def validate_email(email: str) -> bool:
    """Validate email format"""
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def validate_fields(profile: CompanyProfile, performance: PastPerformance) -> List[str]:
    """Validate required fields and return list of issues"""
    issues = []
    
    # Validate company profile fields
    if not profile.company_name:
        issues.append("missing_company_name")
    
    if not profile.uei:
        issues.append("missing_uei")
    
    if not profile.duns:
        issues.append("missing_duns")
    
    if not profile.naics:
        issues.append("missing_naics")
    
    if not profile.poc_name:
        issues.append("missing_poc_name")
    
    if not profile.poc_email:
        issues.append("missing_poc_email")
    elif not validate_email(profile.poc_email):
        issues.append("invalid_poc_email")
    
    if not profile.poc_phone:
        issues.append("missing_poc_phone")
    
    if not profile.address:
        issues.append("missing_address")
    
    if profile.sam_registered is None:
        issues.append("missing_sam_status")
    
    # Validate past performance fields
    if not performance.customer:
        issues.append("missing_customer")
    
    if not performance.contract:
        issues.append("missing_contract")
    
    if not performance.value:
        issues.append("missing_contract_value")
    
    if not performance.period:
        issues.append("missing_contract_period")
    
    if not performance.contact:
        issues.append("missing_contract_contact")
    
    return issues

def map_naics_to_sins(naics_codes: List[str]) -> List[str]:
    """Map NAICS codes to SIN codes"""
    sins = []
    for naics in naics_codes:
        if naics in NAICS_SIN_MAPPING:
            sin = NAICS_SIN_MAPPING[naics]
            if sin not in sins:  # No duplicates
                sins.append(sin)
    return sins

def generate_checklist(profile: CompanyProfile, performance: PastPerformance, issues: List[str]) -> Dict[str, Any]:
    """Generate checklist of required conditions"""
    checklist = {
        "required": {
            "has_company_info": {
                "ok": bool(profile.company_name and profile.uei and profile.duns),
                "details": "Company name, UEI, and DUNS present"
            },
            "has_valid_naics": {
                "ok": bool(profile.naics and len(profile.naics) > 0),
                "details": "At least one NAICS code provided"
            },
            "has_poc_info": {
                "ok": bool(profile.poc_name and profile.poc_email and validate_email(profile.poc_email)),
                "details": "Complete POC information with valid email"
            },
            "has_sam_registration": {
                "ok": profile.sam_registered is True,
                "details": "SAM.gov registration confirmed"
            },
            "has_past_performance": {
                "ok": bool(performance.customer and performance.contract and performance.value),
                "details": "Past performance information provided"
            }
        },
        "overall": {
            "ok": len(issues) == 0,
            "total_issues": len(issues)
        }
    }
    return checklist

@app.post("/ingest")
async def ingest_documents(request: IngestRequest):
    """Main ingest endpoint for processing company profile and past performance documents"""
    request_id = str(uuid.uuid4())
    
    logger.info(f"Processing request {request_id}")
    
    try:
        # Parse documents
        company_profile = parse_company_profile(request.company_profile)
        past_performance = parse_past_performance(request.past_performance)
        
        # Validate fields
        issues = validate_fields(company_profile, past_performance)
        
        # Map NAICS to SINs
        recommended_sins = map_naics_to_sins(company_profile.naics)
        
        # Generate checklist
        checklist = generate_checklist(company_profile, past_performance, issues)
        
        # Prepare response
        response = {
            "request_id": request_id,
            "parsed": {
                "company_profile": company_profile.dict(),
                "past_performance": past_performance.dict()
            },
            "issues": issues,
            "recommended_sins": recommended_sins,
            "checklist": checklist
        }
        
        # Log audit information
        logger.info(f"Request {request_id} - Validations: {len(issues)} issues found")
        logger.info(f"Request {request_id} - Outcome: {'PASS' if len(issues) == 0 else 'FAIL'}")
        logger.info(f"Request {request_id} - Issues: {issues}")
        
        return response
        
    except Exception as e:
        logger.error(f"Request {request_id} - Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")

@app.get("/")
async def read_root():
    return {"message": "GetGSA Coding Test API", "status": "running", "version": "1.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/ui", response_class=HTMLResponse)
async def ui_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

def main():
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

if __name__ == "__main__":
    main()
