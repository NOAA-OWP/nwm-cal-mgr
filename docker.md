# How to use nwm-cal-mgr Docker container

The Dockerfile within this project will allow you to run the nwm-cal-mgr application to execute calibration or validation runs.

## Requirements

> [!CAUTION]
> This is no longer valid as NGWPC GitLab is not accessible/usable by the wider world

To build and run nwm-cal-mgr, you will need the following software installed and running on your system:
- Docker Engine

You will also need files with the following credentials:
- NGWPC gitlab Personal Access Token (PAT): saved to ~/.gitlab_token.

It is recommended you create a ~/ngencerf/data/ngen-cal-data directory to stage configuration and data to run nwm-cal-mgr. The directory structure should look like this:
```
$ tree -L 1
.
├── data
│   └── ngen-cal-data
```

## Building nwm-cal-mgr

To build the nwm-cal-mgr container, execute the following command:
```
docker build --secret id=GITLAB_TOKEN,src=$HOME/.gitlab_token --tag=nwm-cal-mgr .
```

## Running nwm-cal-mgr

To run the nwm-cal-mgr applicaton, execute the following command:
```
docker run -v ~/ngencerf/data/ngen-cal-data/:/ngencerf/data/ nwm-cal-mgr
```

This will print a usage statement for the container:
```
Usage: run-nwm-cal-mgr.sh <operation> <input file>

Required args:
  <operation>         calibration operation, options: create_input, calibration, validation
  <input file>        path to input file for operation
```

The path provided for input file should match the path within the container, so if "input.config" is located at ~/ngencerf/data/ngen-cal-data/input.config, you should run the command:
```
docker run -v ~/ngencerf/data/ngen-cal-data/:/ngencerf/data/ nwm-cal-mgr create_input /ngencerf/data/input.config
```


## Troubleshooting

### Attaching a bash terminal to the container

If there is a need to run a terminal from with in the containerized enviornment, perform the following steps:
1. Get a list of the running containers by executing the following command:
```
docker run -it -v ~/ngencerf/data/ngen-cal-data/:/ngencerf/data/ --entrypoint /bin/bash nwm-cal-mgr
```
2. Execute any needed commands from that terminal.
3. Issue the following command to disconnect:
```
exit
```

## Future Improvements

- Re-instate use of official ngen container build once CFE calibration crashes are resolved.
