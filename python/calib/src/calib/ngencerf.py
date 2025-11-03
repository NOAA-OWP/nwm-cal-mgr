import logging
import os
import time
from urllib.parse import urljoin

import requests

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
NGENCERF_URL = os.environ.get("NGENCERF_URL", "http://localhost:8000/")
NGENCERF_REPORT_ITERATION_ENDPOINT = "calibration/report_iteration/"

# Retry configuration (same semantics as the Bash script)
RETRY_DELAY = 300  # seconds between retries (5 minutes)
MAX_RETRIES = 144  # 12 hours total retry window

logger = logging.getLogger(__name__)


def report(
        calibration_run_id: int,
        iteration: int,
        worker: str,
        first_iteration: bool,
        auth_token: str,
):
    """
    Report a calibration iteration result to the ngenCerf server.

    This function is resilient to temporary network failures:
      - Retries every 5 minutes (up to 12 hours) if the server is unreachable.
      - Immediately exits if a valid HTTP response is received, even if it's an error (4xx/5xx).
    """

    # Construct full URL for the API endpoint
    url = urljoin(NGENCERF_URL, NGENCERF_REPORT_ITERATION_ENDPOINT)

    # Prepare request payload and headers
    payload = {
        "calibration_run_id": calibration_run_id,
        "iteration": iteration,
        "worker_name": worker,
        "first_iteration_for_worker": first_iteration,
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {auth_token}",
    }

    logger.info(f"Reporting iteration to ngenCerf server - {payload}")

    # ─────────────────────────────────────────────────────────────
    # Retry loop:
    # - Only retries on connection-level errors (e.g., server down, DNS failure, refused connection)
    # - Does NOT retry on HTTP responses (e.g., 400, 404, 500) since those mean the server responded
    # ─────────────────────────────────────────────────────────────
    for attempt in range(1, MAX_RETRIES + 1):
        response = None  # ensure it's always defined

        try:
            # Send POST request with a timeout to prevent hanging indefinitely
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            # If we get here, the server responded — check for HTTP errors
            response.raise_for_status()

            # If successful, parse and log the response message
            response_json = response.json()
            message = response_json.get("message")
            logger.info(f"Response from report_iteration: {message}")
            return  # Done, no need to retry

        except requests.exceptions.ConnectionError as e:
            # Server is unreachable (network or DNS issue)
            logger.warning(f"Server unreachable on attempt {attempt}/{MAX_RETRIES}: {e}")

            # Stop after MAX_RETRIES to avoid endless looping
            if attempt >= MAX_RETRIES:
                logger.error("Max retries reached. Giving up.")
                return

            # Wait before retrying
            logger.info(f"Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)

        except requests.exceptions.HTTPError as e:
            # HTTP error: server responded, but with an error code (4xx/5xx)
            # We do NOT retry these because the server is reachable and aware of the request
            logger.error(f"Call to NgenCerf Server {url} failed with {str(e)}.")
            if response is not None:
                logger.error(f"Response from NgenCerf Server: {response.text}")
            return

        except Exception as e:
            # Catch-all for any other unexpected errors (e.g., JSON decoding issue)
            logger.exception(f"Unexpected error while reporting iteration: {e}")
            return
