# Installation

open-law is not published on PyPI yet, and no release has been tagged.
Install it straight from GitHub with [uv](https://docs.astral.sh/uv/) and
pin a commit so the install is reproducible; once releases exist, pin a
tag instead (`@v1.2.3`). The commit used below is only an example — take
the latest one from the
[commit history](https://github.com/politeuma/open-law/commits/main).

## Check your version of python

You will need python 3.11 or later (uv can install one for you). You can
check your version of python by typing into a terminal:

```
$ python3 --version
```

## Run without installing

`uvx` builds a throwaway environment and runs the command in it:

```
$ uvx --from git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a open-law --version
```

## Install the command-line tool

```
$ uv tool install git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a
$ open-law --version
```

Laos publishes its full texts as PDF; extracting them needs the `pdf`
extra:

```
$ uv tool install 'open-law[pdf] @ git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a'
```

## Use it as a library

Add it to a uv-managed project:

```
$ uv add 'open-law @ git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a'
```

or install it into any virtual environment with pip:

```
$ python3 -m pip install 'open-law @ git+https://github.com/politeuma/open-law.git@49ad7b28596f403a5678b7723a6fd8416aec715a'
```

## Set a contact address

Every request carries a User-Agent with a contact address so a site's
operators can reach you. The fetcher refuses to send anything while that
address is still the `contact@example.com` placeholder:

```
$ export FETCHER_CONTACT=you@example.org
```
