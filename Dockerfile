FROM registry.sh.nextgenwaterprediction.com/ngwpc/nwm-ngen/ngen:latest

# ensure local python is preferred over distribution python
ENV PATH="/usr/local/bin:$PATH"

RUN --mount=type=secret,id=GITLAB_TOKEN 
RUN --mount=type=secret,id=GITLAB_TOKEN \ 
    set -eux; \
    \
    git config --global url."https://oauth2:$(cat /run/secrets/GITLAB_TOKEN)@gitlab.sh.nextgenwaterprediction.com/".insteadOf "https://gitlab.sh.nextgenwaterprediction.com/"

COPY . /ngen-app/ngen-cal/

WORKDIR /ngen-app/
RUN set -eux; \
	\
    pip3 install -r ngen-cal/requirements.txt ; \
# Lock numpy and netcdf4 versions so t-route doesn't break
    pip3 install "numpy==1.26.4" "netcdf4<=1.6.3" ; \
    pip3 cache purge

WORKDIR /ngen-app/
RUN set -eux; \
	\
    cd ngen-cal/python/createInput; \
    pip3 install . ; \
    \
    cd ../runCalibValid/ngen_cal; \
    pip3 install . ; \
    \
    cd ../ngen_conf ; \
    pip3 install . ; \
    \
    pip3 cache purge


WORKDIR /
SHELL ["/bin/bash", "-c"]

ENTRYPOINT [ "/bin/bash" ] 

