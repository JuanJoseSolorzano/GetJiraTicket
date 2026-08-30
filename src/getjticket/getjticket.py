import os
import argparse
import re
import sys
import requests
from colored import Fore, Style
from datetime import date
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import TerminalTrueColorFormatter
from requests.auth import HTTPBasicAuth
from rich.console import Console
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore

JIRA_DOMAIN = os.getenv("JIRA_DOMAIN", "")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")

check_env_vars = [JIRA_DOMAIN, JIRA_EMAIL, JIRA_API_TOKEN]
if not all(var != "" for var in check_env_vars):
    print(f"{Fore.RED}Error: One or more required environment variables are missing.{Style.reset}")
    print(f"{Fore.YELLOW}Please set JIRA_DOMAIN, JIRA_EMAIL, and JIRA_API_TOKEN.{Style.reset}")
    sys.exit(1)

TODAY = date.today().strftime("%d/%m/%Y")
ISSUE_KEY = "TDRGDL-%s"

SEPARATOR = "─" * 100
SEPARATOR_2 = "═" * 100
PINK = Fore.rgb("100%", "0%", "60%")
GRAY = Fore.rgb("50%", "50%", "50%")
PARAMS = {"fields": "summary,description,timespent,timeestimate,timetracking,worklog,comment"}
CONSOLE = Console()


def parse_args():
    parser = argparse.ArgumentParser(description="Show Jira issue details.")
    parser.add_argument("issue_id", type=int, help="The ID of the Jira issue (e.g., 6552 for TDRGDL-6552).")
    parser.add_argument("-d", "--description", action="store_true", default=False,
                        help="Show detailed information about the issue.")
    parser.add_argument("-t", "--time", action="store_true", default=False,
                        help="Show time tracking information for the issue.")
    parser.add_argument("-c", "--comment", action="store_true", default=False,
                        help="Get the comments of the issue.")
    return parser.parse_args()


def markup2markdown(text):
    if text is None:
        return "No description provided."

    text = str(text)
    text = re.sub(r'^[-=]{4,}\s*$', '', text, flags=re.MULTILINE)

    for i in range(1, 7):
        text = re.sub(rf'^h{i}\.\s*(.*)$',
                      lambda m: f"{'#' * i} {m.group(1)}",
                      text,
                      flags=re.MULTILINE)

    text = re.sub(r'^\s*\*\s+', '- ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*>\s?', '> ', text, flags=re.MULTILINE)
    text = re.sub(r'\*(.*?)\*', r'**\1**', text)
    text = re.sub(r'_(.*?)_', r'_\1_', text)
    text = re.sub(r'\{\{(.*?)\}\}', r'`\1`', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

def adf_to_text(node):
    if node is None:
        return ""

    if isinstance(node, str):
        return node

    if isinstance(node, list):
        return "\n".join(adf_to_text(item) for item in node)

    if isinstance(node, dict):
        node_type = node.get("type")
        content = node.get("content", [])

        if node_type == "text":
            return node.get("text", "")

        if node_type in ("paragraph", "heading", "blockquote", "listItem"):
            return "\n".join(filter(None, (adf_to_text(item) for item in content)))

        if node_type in ("bulletList", "orderedList", "doc"):
            return "\n".join(filter(None, (adf_to_text(item) for item in content)))

        return "\n".join(filter(None, (adf_to_text(item) for item in content)))

    return str(node)


def normalize_text(value):
    if isinstance(value, (dict, list)):
        return adf_to_text(value)
    return "" if value is None else str(value)


def connect_jira(issue_id: str) -> requests.Response:
    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue/{ISSUE_KEY % issue_id}"
    return requests.get(
        url,
        params=PARAMS,
        auth=HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
        verify=False
    )


def get_time_tracking_info(fields, link_to_issue, issue_id) -> None:
    worklogs = fields["worklog"]["worklogs"]
    estimated = fields["timetracking"].get("originalEstimate", "0s")
    remaining = fields["timetracking"].get("remainingEstimate", "0s")
    time_spent = fields["timetracking"].get("timeSpent", "0s")

    print(SEPARATOR)
    print(f"Issue ID: {ISSUE_KEY % issue_id}")
    print(f"Summary: {fields['summary']}")
    print(f"Link to Issue: {link_to_issue}")
    print(" ")
    print(f"{'':<25}[- TIME TRACKING INFORMATION -]")
    print(" ")
    print(f"{'Original Estimate:':<20} {estimated}")
    print(f"{'Remaining Time:':<20} {remaining}")
    print(f"{'Time Spent:':<20} {time_spent}")

    print(SEPARATOR_2)
    print(f"{'Author':<25} {'Started':<20} {'Time Spent':<12} Comment")
    print(SEPARATOR)

    for worklogged in worklogs:
        author = worklogged["author"]["displayName"]
        spent = worklogged["timeSpent"]
        started = worklogged["started"].replace("T", " ").replace(".000+0000", "")
        comment = normalize_text(worklogged.get("comment", ""))
        comment = comment[:50] + "..." if len(comment) > 50 else comment
        print(f"{author:<25} {started:<20} {spent:<12} {comment}")

    print(SEPARATOR_2)


def get_description(fields, link_to_issue, issue_id) -> None:
    description = normalize_text(fields.get("description"))
    cleaned = markup2markdown(description)
    lexer = get_lexer_by_name("markdown", stripall=True)
    colored_output = highlight(cleaned, lexer, TerminalTrueColorFormatter()).splitlines()

    print(SEPARATOR_2)
    print(f"  {GRAY}{ISSUE_KEY % issue_id} - {fields['summary']}")
    print(f"  [{link_to_issue}]{Style.reset}")
    print(SEPARATOR)

    for line_number, line in enumerate(colored_output, start=1):
        print(f"{GRAY}{line_number:<2}│ {Style.reset}{line}")

    print(SEPARATOR_2)


def get_comments(fields, link_to_issue, issue_id) -> None:
    comments = fields["comment"]["comments"]

    print(SEPARATOR_2)
    print(f"  {GRAY}{ISSUE_KEY % issue_id} - {fields['summary']}")
    print(f"  [{link_to_issue}]{Style.reset}")
    print(SEPARATOR)

    for comment in comments:
        author = comment["author"]["displayName"]
        created = comment["created"].replace("T", " ").replace(".000+0000", "")
        body = markup2markdown(normalize_text(comment.get("body")))
        lexer = get_lexer_by_name("markdown", stripall=True)
        colored_output = highlight(body, lexer, TerminalTrueColorFormatter()).splitlines()

        print(f"{PINK}{author} commented on {created}:{Style.reset}")
        for line_number, line in enumerate(colored_output, start=1):
            print(f"{GRAY}{line_number:<2}│ {Style.reset}{line}")
        print(SEPARATOR)

    print(SEPARATOR_2)

def run() -> None:
    args = parse_args()
    issue_id = args.issue_id
    link_to_issue = f"https://{JIRA_DOMAIN}/browse/{ISSUE_KEY % issue_id}"

    response = connect_jira(issue_id).json()
    fields = response["fields"]

    if args.description:
        get_description(fields, link_to_issue, issue_id)
    elif args.time:
        get_time_tracking_info(fields, link_to_issue, issue_id)
    elif args.comment:
        get_comments(fields, link_to_issue, issue_id)
    else:
        get_description(fields, link_to_issue, issue_id)
        get_time_tracking_info(fields, link_to_issue, issue_id)

if __name__ == "__main__":
    run()