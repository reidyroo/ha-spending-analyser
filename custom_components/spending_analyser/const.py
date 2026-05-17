"""Constants for the HA Spending Analyser integration."""

DOMAIN = "spending_analyser"
VERSION = "0.2.0"

# Config entry keys
CONF_OLLAMA_HOST = "ollama_host"
CONF_OLLAMA_MODEL = "ollama_model"
CONF_OLLAMA_PORT = "ollama_port"
CONF_DB_PATH = "db_path"

# Defaults
DEFAULT_OLLAMA_HOST = "localhost"
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_OLLAMA_MODEL = "phi3:mini"
DEFAULT_DB_NAME = "spending_analyser.db"

# Service names
SERVICE_IMPORT_STATEMENT = "import_statement"
SERVICE_ADD_TRANSACTION = "add_transaction"
SERVICE_RECATEGORISE = "recategorise"
SERVICE_GENERATE_REPORT = "generate_report"

# Supported import formats
IMPORT_FORMAT_CSV = "csv"
IMPORT_FORMAT_OFX = "ofx"
IMPORT_FORMAT_QIF = "qif"
SUPPORTED_FORMATS = [IMPORT_FORMAT_CSV, IMPORT_FORMAT_OFX, IMPORT_FORMAT_QIF]

# Default spending categories
DEFAULT_CATEGORIES = [
    "Groceries",
    "Dining & Takeaway",
    "Transport",
    "Fuel",
    "Utilities",
    "Rent & Mortgage",
    "Health & Medical",
    "Insurance",
    "Entertainment",
    "Shopping & Clothing",
    "Travel",
    "Education",
    "Personal Care",
    "Home & Garden",
    "Technology",
    "Subscriptions",
    "Savings & Investments",
    "Income",
    "Transfer",
    "Uncategorised",
]

# Sensor update interval (minutes)
SENSOR_UPDATE_INTERVAL = 15

# Platforms
PLATFORMS = ["sensor"]
