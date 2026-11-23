import json
from aios_rebuild.privacy_core import PrivacyCore

ROUTER_DB_PATH = r"L:\LocalCoder\workspace\aios_rebuild\memory\aios_router\router.sqlite3"
AUTONOMY_DIR_PATH = r"L:\LocalCoder\workspace\autonomy"

def check_authorization():
    """Check if router database path is allowed by PrivacyCore."""
    result = {"allowed": False, "reason": ""}
    
    try:
        # Check if the specific router DB path is authorized
        auth_result = PrivacyCore.authorize_file_write(ROUTER_DB_PATH)
        
        if auth_result["decision"] == True:
            result["allowed"] = True
            result["reason"] = "Router database path is allowed by PrivacyCore policy"
        else:
            result["allowed"] = False
            result["reason"] = f"Router database path denied: {auth_result.get('reason', 'Unknown reason')}"
    except Exception as e:
        result["allowed"] = False
        result["reason"] = f"Authorization check failed: {str(e)}"
    
    # Verify the autonomy directory is NOT allowed (should be denied)
    try:
        auth_result_autonomy = PrivacyCore.authorize_file_write(AUTONOMY_DIR_PATH)
        
        if auth_result_autonomy["decision"] == True:
            result["autonomy_dir_allowed"] = True
            result["reason"] += f"; Autonomy directory unexpectedly allowed"
        else:
            result["autonomy_dir_allowed"] = False
            result["reason"] += "; Autonomy directory correctly denied (as expected)"
    except Exception as e:
        result["autonomy_dir_allowed"] = False
        result["reason"] += f"; Autonomy directory check failed: {str(e)}"
    
    return result

if __name__ == "__main__":
    result = check_authorization()
    print(json.dumps(result, indent=2))