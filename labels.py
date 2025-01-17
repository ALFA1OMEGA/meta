#!/usr/bin/env python

import argparse, base64, json, re, urllib, requests
from review import fetch_json, find_shortnames


def get_labels(labels_resource):
    return json.load(open(labels_resource, "r"))

def remove_markdown_links(input):
    return re.sub(r"\[(.+)\]\(.+\)", r"\1", input)

def lint_labels(labels):
    for label in labels:
        if "name" not in label:
            print("A label needs a name")
        elif "description" not in label:
            print("A label (" + label["name"] + ") needs a description")
        elif len(remove_markdown_links(label["description"])) > 100:
            print("GitHub will likely complain about the length of your label (" + label["name"] + ")'s description.")
        elif "color" not in label:
            print("A label (" + label["name"] + ") needs a color")
        elif "url_exclude_is_open" in label and label["url_exclude_is_open"] != True:
            print("A label (" + label["name"] + ")'s url_exclude_is_open needs to be set to true if present.")
        elif "w3c" in label and label["w3c"] != True:
            print("A label (" + label["name"] + ")'s w3c needs to be set to true if present.")

def import_w3c_labels(labels_resource):
    # Get W3C labels from their canonical URL
    w3c_labels = fetch_json("https://w3c.github.io/hr-labels.json")

    # Create a name index for the W3C labels
    w3c_label_index = {}
    i = 0
    for label in w3c_labels:
        w3c_label_index[label["name"]] = i
        i += 1

    # Update local entries with new upstream information
    local_labels = get_labels(labels_resource)
    i = 0
    for label in local_labels:
        if label["name"] in w3c_label_index:
            w3c_index = w3c_label_index[label["name"]]
            local_labels[i]["description"] = w3c_labels[w3c_index]["description"]
            local_labels[i]["color"] = w3c_labels[w3c_index]["color"].lower()
            local_labels[i]["w3c"] = True
            del w3c_label_index[label["name"]]
        elif "w3c" in local_labels[i]:
            assert False, "W3C label present that's no longer upstream"
        i += 1

    # Add new upstream information
    for w3c_label_name in w3c_label_index:
        w3c_index = w3c_label_index[w3c_label_name]
        local_labels.append({
            "name": w3c_labels[w3c_index]["name"],
            "description": w3c_labels[w3c_index]["description"],
            "color": w3c_labels[w3c_index]["color"].lower(),
            "w3c": True
        })

    # Write it all to disk
    update_labels(local_labels, labels_resource)

def update_labels(labels, labels_resource):
    lint_labels(labels)
    labels.sort(key=lambda x: x["name"])
    handle = open(labels_resource, "w")
    handle.write(json.dumps(labels, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2, separators=(',', ': ')))
    handle.write("\n")
    create_labels_docs(labels)

def create_labels_docs(labels):
    output = """<!-- Please do not edit this file directly. It is generated by labels.py -->

# GitHub Labels

These are labels used by all [WHATWG standards](https://spec.whatwg.org/):

"""
    for label in labels:
        if "w3c" in label:
            continue
        output += format_label(label)
    output += "\n"
    output += "The following [W3C horizontal labels](https://w3c.github.io/issue-metadata.html#horizontal-reviews) can also be used:\n\n"
    for label in labels:
        if "w3c" not in label:
            continue
        output += format_label(label)

    handle = open("LABELS.md", "w")
    handle.write(output)

def format_label(label):
    url = "https://github.com/search?q=org%3Awhatwg+label%3A%22" + urllib.parse.quote_plus(label["name"]) + "%22"
    if not "url_exclude_is_open" in label:
        url += "+is%3Aopen"
    return "* [{}]({}): {}\n".format(label["name"], url, label["description"])


def fetch(token, url, method, body=None):
    return requests.request(method, url, data=body, headers={
        b"Authorization": b"Basic " + base64.b64encode(bytes(token, encoding="utf-8") + b":x-oauth-basic").replace(b"\n", b""),
        b"Accept": b"application/vnd.github.v3+json"
    })

def label_name_url(common_url, label_name):
    # Note: this uses quote() instead of quote_plus() as spaces need to become %20 here
    return common_url + "/" + urllib.parse.quote(label_name)

def error(type, label_name, status):
    print(type + " label: " + label_name + "; status " + str(status))

def delete_label(common_url, token, label_name):
    r = fetch(token, label_name_url(common_url, label_name), "DELETE")
    if r.status_code != 200 and r.status_code != 404:
        error("Deleting", label_name, r.status_code)

def update_label(common_url, token, label):
    # Note: this returns the response so the caller can branch.
    body = json.dumps(label)
    return fetch(token, label_name_url(common_url, label["name"]), "PATCH", body)

def add_label(common_url, token, label):
    body = json.dumps(label)
    r = fetch(token, common_url, "POST", body)
    if r.status_code != 201:
        error("Adding", label["name"], r.status_code)

def adjust_repository_labels(organization, repository, token, labels_resource):
    common_url = "https://api.github.com/repos/%s/%s/labels" % (organization, repository)

    # Delete default GitHub labels except for "good first issue"
    for label_name in ("bug", "duplicate", "enhancement", "help wanted", "invalid", "question", "wontfix"):
        delete_label(common_url, token, label_name)

    # Update and add labels
    labels = get_labels(labels_resource)
    lint_labels(labels)
    for label in labels:
        label["description"] = remove_markdown_links(label["description"])
        if "url_exclude_is_open" in label:
            del label["url_exclude_is_open"]
        r = update_label(common_url, token, label)
        if r.status_code == 404:
            add_label(common_url, token, label)
        elif r.status_code != 200:
            error("Updating", label["name"], r.status_code)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-w3c", action="store_true", help="imports labels from the W3C")
    parser.add_argument("--update", action="store_true", help="sort JSON entries and update Markdown documentation")
    parser.add_argument("--repository", help="update labels on a single repository, e.g., whatwg/fetch; requires --token")
    parser.add_argument("--all-whatwg-standards", action="store_true", help="update labels on all WHATWG standards; requires --token")
    parser.add_argument("--token", help="a GitHub token that allows you to modify labels on WHATWG repositories")
    args = parser.parse_args()

    labels_resource = "labels.json"

    if args.import_w3c:
        import_w3c_labels(labels_resource)
    elif args.update:
        labels = get_labels(labels_resource)
        update_labels(labels, labels_resource)
    elif args.repository and "/" in args.repository and args.token:
        [organization, repository] = args.repository.split("/")
        adjust_repository_labels(organization, repository, args.token, labels_resource)
    elif args.all_whatwg_standards and args.token:
        # It would be slightly neater to instead pull the repositories from a JSON resource so this
        # script would remain WHATWG-agnostic, but we don't have a good JSON resource for this so
        # far.
        db = fetch_json("https://github.com/whatwg/sg/raw/main/db.json")
        for repository in find_shortnames(db["workstreams"]):
            # Give a little bit of output as otherwise it's hard to tell what's going on
            print("About to process", repository)
            adjust_repository_labels("whatwg", repository, args.token, labels_resource)
    else:
        parser.print_usage()

main()
