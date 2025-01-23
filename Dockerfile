ARG IMAGE_TAG=latest
FROM registry.sh.nextgenwaterprediction.com/ngwpc/nwm-ngen/ngen:${IMAGE_TAG}

RUN --mount=type=secret,id=GITLAB_TOKEN \ 
    set -eux; \
    \
    git config --global url."https://oauth2:$(cat /run/secrets/GITLAB_TOKEN)@gitlab.sh.nextgenwaterprediction.com/".insteadOf "https://gitlab.sh.nextgenwaterprediction.com/"

COPY . /ngen-app/ngen-cal/

COPY ./docker/run-ngen-cal.sh /ngen-app/bin/

WORKDIR /ngen-app/

RUN set -eux; \
	\
    chmod +x /ngen-app/bin/run-ngen-cal.sh

RUN set -eux; \
	\
    pip3 install -r ngen-cal/requirements.txt ; \
# Lock numpy and netcdf4 versions so t-route doesn't break
    pip3 install "numpy==1.26.4" "netcdf4<=1.6.3" ; \
    pip3 install "hydrotools.events==1.1.5" "hydrotools.nwis-client==3.3.1" ; \
    pip3 cache purge

WORKDIR /ngen-app/
RUN set -eux; \
	\
    cd ngen-cal/python/createInput; \
    # Reset cache to ensure latest updates are captured
    touch src/*.py; \
    pip3 install . ; \
    \
    cd ../runCalibValid/ngen_cal; \
    touch src/ngen/cal/*.py; \
    pip3 install . ; \
    \
    cd ../ngen_conf ; \
    touch src/ngen/config/*.py; \
    pip3 install . ; \
    \
    pip3 cache purge ; \
    rm --force /root/.gitconfig
 

WORKDIR /

ENTRYPOINT [ "/ngen-app/bin/run-ngen-cal.sh" ] 
