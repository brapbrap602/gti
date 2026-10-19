import os
import sys

from loguru import logger

logs_dir = "../logs"
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)
# Configure logger to display only INFO level and above to the terminal
logger.remove()
logger.add(sys.stdout, level="INFO")

# Configure logger to write all levels to a file, with a new file created every day at midnight
logger.add("logs/{time:YYYY-MM-DD}.log", rotation="1 day", compression="zip")
