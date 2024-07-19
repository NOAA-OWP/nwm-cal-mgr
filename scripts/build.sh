#!/bin/bash

PROJECT_NAME="ngen-cal"
BUILD_DIR="/ngen-app"
INSTALL_DIR="/ngen-app/opt"

dnf install -y epel-release
dnf config-manager --set-enabled powertools
dnf install -y git gcc-toolset-10 gcc-toolset-10-libasan-devel curl sqlite sqlite-devel openssl-devel libffi-devel

mkdir -p $INSTALL_DIR
cd $INSTALL_DIR
curl -L -O https://www.python.org/ftp/python/3.10.14/Python-3.10.14.tgz
tar xzf Python-3.10.14.tgz
scl enable gcc-toolset-10 bash <<EOF
   cd Python-3.10.14
   ./configure --enable-optimizations --with-lto --enable-shared --prefix=$INSTALL_DIR
   make -s -j 4
   make install
EOF

export PATH="${INSTALL_DIR}/bin":$PATH
export LD_LIBRARY_PATH="${INSTALL_DIR}/lib":$LD_LIBRARY_PATH

mkdir -p "${BUILD_DIR}/${PROJECT_NAME}-python"
cd $BUILD_DIR
python3.10 -m venv --system-site-packages "${PROJECT_NAME}-python"
source "${PROJECT_NAME}-python/bin/activate"

cd "${BUILD_DIR}/${PROJECT_NAME}"
pip3 install -r requirements.txt
git config --global url."https://oauth2:${GITLAB_TOKEN}@gitlab.sh.nextgenwaterprediction.com/".insteadOf "https://gitlab.sh.nextgenwaterprediction.com/"
pip3 install "git+https://gitlab.sh.nextgenwaterprediction.com/NGWPC/nwm-ngen/ngen-cal/@master#egg=ngen_cal&subdirectory=python/ngen_cal"
