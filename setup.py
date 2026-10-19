import os

from setuptools import find_packages, setup

# 引擎包名与项目同名。容器内工作目录（DC_HOME）也用这个名字，
# 见 Dockerfile 与 docker/entrypoint.sh。
NAME = "unicheckin"
FOLDER = "unicheckin"
DESCRIPTION = "签到聚合 + 网页管理面板"
EMAIL = "zonbar@users.noreply.github.com"
AUTHOR = "zonbar"
REQUIRES_PYTHON = ">=3.9.0"
URL = "https://github.com/zonbar/unicheckin"
VERSION = None


def read_file(filename):
    with open(filename) as fp:
        return fp.read().strip()


def read_requirements(filename):
    return [line.strip() for line in read_file(filename).splitlines() if not line.startswith("#")]


REQUIRED = read_requirements("requirements.txt")

here = os.path.abspath(os.path.dirname(__file__))

try:
    with open(os.path.join(here, "README.md"), encoding="utf-8") as f:
        long_description = "\n" + f.read()
except FileNotFoundError:
    long_description = DESCRIPTION

about = {}
if not VERSION:
    with open(os.path.join(here, FOLDER, "__version__.py")) as f:
        exec(f.read(), about)
else:
    about["__version__"] = VERSION


def package_files(directories):
    paths = []
    for item in directories:
        if os.path.isfile(item):
            paths.append(os.path.join("..", item))
            continue
        for path, _, filenames in os.walk(item):
            for filename in filenames:
                paths.append(os.path.join("..", path, filename))
    return paths


setup(
    name=NAME,
    version=about["__version__"],
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type="text/markdown",
    author=AUTHOR,
    author_email=EMAIL,
    python_requires=REQUIRES_PYTHON,
    url=URL,
    project_urls={
        "Source": URL,
        "Issue": URL + "/issues",
    },
    packages=find_packages(exclude=("config", "panel")),
    install_requires=REQUIRED,
    include_package_data=True,
    license="MIT",
    zip_safe=False,
    entry_points={"console_scripts": ["unicheckin = unicheckin.main:checkin"]},
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
    ],
)
