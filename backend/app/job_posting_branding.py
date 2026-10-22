"""Company-owned posting details, shared by the UI defaults and publisher."""
import re

COMPANY_NAME = "BJIT"
POST_HEADING = "BJIT is Hiring!"
CONTACT_EMAIL = "sohail.sh.ahmed@gmail.com"
COMPANY_ADDRESS = "House-5/B, Road-2/E, Block-J, Baridhara, Dhaka 1212"


def posting_description(content: str) -> str:
    """Correct the known reference-employer alias without changing saved JDs."""
    return re.sub(r"\bNorthstar\s+Digital\b", COMPANY_NAME, content, flags=re.IGNORECASE)
