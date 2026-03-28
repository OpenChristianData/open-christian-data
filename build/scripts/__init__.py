# This __init__.py makes build/scripts/ a Python package.
# Required so that validate.py can import build.scripts.validate_osis via:
#   sys.path.insert(0, str(REPO_ROOT))
#   from build.scripts.validate_osis import validate_osis_array
# Do not remove -- the import chain is: REPO_ROOT in sys.path -> build/__init__.py -> this file.
