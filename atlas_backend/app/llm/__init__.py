"""Language models: the providers, the local runtime, and which one answers.

    base.py              what a provider is
    anthropic_provider   Claude, over the cloud API
    ollama_provider      a model running on this machine
    ollama_client        HTTP to the local Ollama daemon
    translate.py         our stored history <-> Ollama's chat format
    catalogue.py         the models offered on the Models page
    inventory.py         what is installed, and what it can do
    selection.py         which provider and model are in force
    providers.py         building the one in force

Kept import-free so the modules inside can import each other freely.
"""
