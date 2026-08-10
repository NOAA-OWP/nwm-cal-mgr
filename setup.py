"""Top-level setup for NWM Calibration Manager with scripts."""

from pathlib import Path
from setuptools import setup, find_packages

# Load dependencies from both subdirectory requirements
def load_requirements(*paths):
    """Load and merge requirements from multiple files."""
    requirements = set()
    for path in paths:
        req_path = Path(__file__).parent / path
        if req_path.exists():
            for line in req_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    requirements.add(line)
    return sorted(requirements)

install_requires = load_requirements(
    "python/calib/requirements.txt",
    "python/config/requirements.txt",
)

# Find packages from both src directories
calib_packages = find_packages(where="python/calib/src")
config_packages = find_packages(where="python/config/src")
all_packages = calib_packages + config_packages

# Build package_dir mapping
package_dir = {
    "": "python",  # Root directory for py_modules (the standalone scripts)
}
for pkg in calib_packages:
    package_dir[pkg] = "python/calib/src/" + pkg
for pkg in config_packages:
    package_dir[pkg] = "python/config/src/" + pkg

setup(
    name="nwm-cal-mgr",
    version="0.3.0",
    author="OWP & Raytheon",
    author_email="yuqiong.liu@ertcorp.com",
    description="NWM Calibration Manager with calib, config packages and executable scripts",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/NGWPC/nwm-cal-mgr",
    # Packages from both calib and config src directories
    packages=all_packages,
    package_dir=package_dir,
    # Add the standalone script modules from python/ directory
    py_modules=["calibration", "validation", "validation_iteration"],
    include_package_data=True,
    install_requires=install_requires,
    # Use entry_points for console scripts
    entry_points={
        "console_scripts": [
            "calibration=calibration:cli",
            "validation=validation:cli",
            "validation_iteration=validation_iteration:cli",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.11",
)
