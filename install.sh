#$/bin/sh
set -e 
set -o pipefail

DIPDUP_CWD=`pwd`
DIPDUP_CACHE=/tmp/dipdup_install
DIPDUP_VERSION=aux/arm64

echo "==> Welcome to the DipDup Installer"
mkdir -p $DIPDUP_CACHE
cd $DIPDUP_CACHE

echo "==> Checking for dependencies"
for dep in python git make poetry; do
    if ! command -v $dep &> /dev/null
    then
        echo "`$dep` not found. Please install it and try again."
        exit
    fi
done

echo "==> Installing cookiecutter"
python -m venv .venv
source .venv/bin/activate
pip install -qU pip
pip install -qU cookiecutter
cd $DIPDUP_CWD

echo "==> Creating DipDup project"
cookiecutter -f https://github.com/dipdup-net/dipdup-py -c $DIPDUP_VERSION --directory cookiecutter
deactivate

for dir in `ls -d */ | grep -v cookiecutter`; do
    if [[ -f "$dir/dipdup.yml" ]] && [[ ! -f "$dir/poetry.lock" ]]; then
        echo "==> Running initial DipDup setup"
        cd $dir
        git init | sed -e 's/^/> /;'
        make install | sed -e 's/^/> /;'
        echo "==> Verifying DipDup setup"
        make lint | sed -e 's/^/> /;'
        break
    fi
done

echo "==> Cleaning up"
rm -r $DIPDUP_CACHE

echo "==> Done! DipDup is ready to use."
