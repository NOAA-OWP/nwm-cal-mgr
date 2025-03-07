ARG IMAGE_TAG=latest
ARG CI_COMMIT_REF_NAME
FROM registry.sh.nextgenwaterprediction.com/ngwpc/nwm-ngen/ngen:${IMAGE_TAG}
# Uncomment when building ngen locallay
# FROM ngen

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
    rm --force /root/.gitconfig ;

WORKDIR /ngen-app/ngen-cal

# Extract Git information and write it to the JSON file specified by $GIT_INFO_PATH
ARG GIT_INFO_PATH=/ngen-app/ngen-cal_git_info.json

RUN set -eux; \
    echo "CI_COMMIT_REF_NAME: ${CI_COMMIT_REF_NAME:-not set}"; \
    # Determine branch name: if CI_COMMIT_REF_NAME is set (CI build), use it; otherwise, fall back to using the git command for manual builds.
    branch=$( [ -n "${CI_COMMIT_REF_NAME:-}" ] && echo "${CI_COMMIT_REF_NAME}" || git rev-parse --abbrev-ref HEAD ); \
    echo "Determined branch: $branch"; \
    jq -n \
      --arg commit_hash "$(git rev-parse HEAD)" \
      --arg branch "$branch" \
      --arg tags "$(git tag --points-at HEAD | tr '\n' ' ')" \
      --arg author "$(git log -1 --pretty=format:'%an')" \
      --arg commit_date "$(date -u -d @$(git log -1 --pretty=format:'%ct') +'%Y-%m-%d %H:%M:%S UTC')" \
      --arg message "$(git log -1 --pretty=format:'%s' | tr '\n' ';')" \
      --arg build_date "$(date -u +'%Y-%m-%d %H:%M:%S UTC')" \
      '{"ngen-cal": {commit_hash: $commit_hash, branch: $branch, tags: $tags, author: $author, commit_date: $commit_date, message: $message, build_date: $build_date}}' \
      > $GIT_INFO_PATH

WORKDIR /

ENTRYPOINT [ "/ngen-app/bin/run-ngen-cal.sh" ] 
