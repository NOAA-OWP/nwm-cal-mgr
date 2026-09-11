import requests
import time
from common import get_calmgr_logger
from urllib.parse import urlparse


class ReportIterationError(RuntimeError):
    pass


def _logger():
    return get_calmgr_logger()


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
# Resource path only (leading slash, NO /api). The /api prefix is a routing
# artifact (it splits UI vs server traffic on the shared ALB), so it lives in
# the base URL the server hands us — ngencerf_base_url already ends in /api,
# the same place the UI, CLI, and the server's own Slurm callbacks keep it. We
# join by plain string concatenation against the trailing-slash-stripped base
# (the one shared join convention), so /api appears exactly once.
NGENCERF_REPORT_ITERATION_ENDPOINT = "/calibration/report_iteration/"

# Retry configuration (same semantics as the Bash script)
RETRY_DELAY = 300  # seconds between retries (5 minutes)
MAX_RETRIES = 144  # 12 hours total retry window


def report(
        calibration_run_id: int,
        iteration: int,
        worker: str,
        first_iteration: bool,
        auth_token: str,
        ngencerf_base_url: str
) -> None:
    """
    Report a calibration iteration result to the ngenCerf server.

    This function is resilient to temporary network failures:
      - Retries every 5 minutes, up to 12 hours, if the server is unreachable.
      - Does not retry HTTP responses such as 400, 404, or 500, because those
        mean the server received the request and returned an application-level
        or server-side error.
      - Raises a fatal exception if the report cannot be posted successfully.
    """
    url = (
            ngencerf_base_url.rstrip("/")
            + NGENCERF_REPORT_ITERATION_ENDPOINT
    )

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

    _logger().info(f"Reporting iteration to ngenCerf server - url={url}, payload={payload}")

    # ─────────────────────────────────────────────────────────────
    # Retry loop:
    # - Only retries connection-level errors, such as server down, DNS failure,
    #   refused connection, or request timeout.
    # - Does NOT retry HTTP responses, such as 400, 404, or 500, because those
    #   mean the server responded. Retrying the same invalid request is unlikely
    #   to fix the problem and could hide the real failure.
    # - Raises a fatal exception if the iteration report is not accepted.
    # ─────────────────────────────────────────────────────────────
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _logger().info(f"Reporting iteration to {url} - payload: {payload}")

            # Send POST request with a timeout to prevent hanging indefinitely
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            # If we get here, the server responded. Check for HTTP errors.
            response.raise_for_status()

            # If successful, parse and log the response message
            try:
                response_json = response.json()
            except ValueError as e:
                raise ReportIterationError(
                    f"Invalid JSON response from ngenCerf server: url={url}, "
                    f"status_code={response.status_code}, response={response.text}"
                ) from e

            message = response_json.get("message")
            _logger().info(f"Response from report_iteration: {message}")
            return  # Done, no need to retry

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            # Server is unreachable or did not respond within the timeout
            _logger().warning(f"Server unreachable on attempt {attempt}/{MAX_RETRIES}: {e}")

            # Stop after MAX_RETRIES to avoid endless looping
            if attempt >= MAX_RETRIES:
                raise ReportIterationError(
                    f"Failed to report iteration after {MAX_RETRIES} attempts: "
                    f"url={url}, payload={payload}"
                ) from e

            # Wait before retrying
            _logger().info(f"Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)

        except requests.exceptions.HTTPError as e:
            http_response = e.response
            status_code = http_response.status_code if http_response is not None else "<unknown>"
            response_text = http_response.text if http_response is not None else "<no response body>"

            # Server responded with an HTTP error. Do not retry.
            raise ReportIterationError(
                f"Call to ngenCerf server failed: "
                f"url={url}, status_code={status_code}, response={response_text}"
            ) from e

        except Exception as e:
            raise ReportIterationError(
                f"Unexpected error while reporting iteration: url={url}, payload={payload}"
            ) from e
