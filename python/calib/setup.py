"""Function for setting up regionalization."""

from pathlib import Path

from setuptools import find_packages, setup

# Load dependencies from requirements.txt
requirements_path = Path(__file__).with_name("requirements.txt")
install_requires = []
if requirements_path.exists():
    install_requires = [
        line.strip()
        for line in requirements_path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="calib",
    version="0.3.0",
    author="OWP & Raytheon",
    author_email="yuqiong.liu@ertcorp.com",
    description="NWM Calibration Manager (calib package)",
    long_description=open("../../README.md").read(),
    long_description_content_type="text/markdown",
    url="https://gitlab.sh.nextgenwaterprediction.com/NGWPC/nwm-ngen/ngen-cal/python/calib",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    install_requires=install_requires,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.10",
)
