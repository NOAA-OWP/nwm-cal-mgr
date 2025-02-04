import logging
from urllib.parse import urljoin
import requests
import os 

NGENCERF_URL = os.environ.get('NGENCERF_URL', 'http://localhost:8000/')
NGENCERF_REPORT_ITERATION_ENDPOINT = 'calibration/report_iteration/'

logger = logging.getLogger(__name__)

def report(calibration_run_id: int, iteration: int, worker: str, first_iteration: bool, auth_token: str):

    url = urljoin(NGENCERF_URL, NGENCERF_REPORT_ITERATION_ENDPOINT)
    payload = {
        'calibration_run_id': calibration_run_id,
        'iteration': iteration,
        'worker_name': worker,
        'first_iteration_for_worker': first_iteration
    }    
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {auth_token}"
    }

    logger.info(f'Reporting iteration to ngenCerf server - {payload}')
    response = requests.post(url, json=payload, headers=headers)
    
    try:
        response.raise_for_status()
        response_json = response.json()
        message = response_json.get('message')
        logger.info(f'Response from report_iteration: {message}')
    except requests.exceptions.HTTPError as e:
        logger.error(f"Call to NgenCerf Server {url} failed with {str(e)}.")
        logger.error(f"Response from NgenCerf Server: {response.text}")
        return

