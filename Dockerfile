FROM ngen:latest

# ensure local python is preferred over distribution python
ENV PATH="/usr/local/bin:$PATH"

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

