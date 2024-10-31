import argparse
import createInput

# Create command line parser to supply input config file
parser = argparse.ArgumentParser()
parser.add_argument('input_config', type=str, help='input configuration file')
args = parser.parse_args()

try:
    createInput.create_input(args.input_config)
except Exception as e:
    print(f"ERROR: uncaught exception: {e}")
