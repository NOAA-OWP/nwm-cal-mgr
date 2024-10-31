# How to use ngen-cal Docker container

The Dockerfile within this project will allow you to run the ngen-cal application to execute calibration or validation runs.

## Requirements

To build and run ngen-cal, you will need the following software installed and running on your system:
- Docker Engine

You will also need files with the following credentials:
- NGWPC gitlab Personal Access Token (PAT): saved to ~/.gitlab_token.

It is recommended you create a ~/ngencerf/data/ngen-cal-data directory to stage configuration and data to run ngen-cal. The directory structure should look like this:
```
$ tree -L 1
.
├── data
│   └── ngen-cal-data
```

## Building ngen-cal

To build the ngen-cal container, execute the following command:
```
docker build --secret id=GITLAB_TOKEN,src=$HOME/.gitlab_token --tag=ngen-cal .
```

## Running ngen-cal

To run the ngen-cal applicaton, execute the following command:
```
docker run -v ~/ngencerf/data/ngen-cal-data/:/ngencerf/data/ ngen-cal
```

This will print a usage statement for the container:
```
Usage: run-ngen-cal.sh <operation> <input file>

Required args:
  <operation>         calibration operation, options: create_input, calibration, validation
  <input file>        path to input file for operation
```

The path provided for input file should match the path within the container, so if "input.config" is located at ~/ngencerf/data/ngen-cal-data/input.config, you should run the command:
```
docker run -v ~/ngencerf/data/ngen-cal-data/:/ngencerf/data/ ngen-cal create_input /ngencerf/data/input.config
```


## Troubleshooting

### Attaching a bash terminal to the container

If there is a need to run a terminal from with in the containerized enviornment, perform the following steps:
1. Get a list of the running containers by executing the following command:
```
docker run -it -v ~/ngencerf/data/ngen-cal-data/:/ngencerf/data/ --entrypoint /bin/bash ngen-cal
```
2. Execute any needed commands from that terminal.
3. Issue the following command to disconnect:
```
exit
```

## Future Improvements 

- Re-instate use of official ngen container build once CFE calibration crashes are resolved.
