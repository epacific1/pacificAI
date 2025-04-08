import subprocess
import ollama
import yaml
import re
import os
from copy import deepcopy


def strip_ansi_codes(text):
    """Removes ANSI escape codes from the text."""
    # This regex will match the ANSI escape sequences, including hyperlinks
    ansi_escape = re.compile(r'(\x1b\[\d+;\d+;\d+m|\x1b\[\d+m|\x1b]8;[^\x1b]*\x1b\\|\x1b\[[0-9;]*[a-zA-Z])')
    return ansi_escape.sub('', text)


def clean_and_group_lint_issues(cleaned_output):
    # Split by double newlines to separate individual lint issues
    lint_issues = cleaned_output.strip().split("\n\n")

    # Now we'll create a dictionary with the issues, where the key could be an incremented number or the file name/line as an identifier.
    lint_issues_dict = {}

    for index, issue in enumerate(lint_issues):
        # You can use 'index' as a simple key or use some other way to identify each issue
        lint_issues_dict[f"issue_{index + 1}"] = issue

    return lint_issues_dict

def process_lint_output(cleaned_output):
    """Processes the cleaned lint output and groups every 3 lines into an issue dictionary."""
    lint_issues = {}
    lines = cleaned_output.splitlines()

    # Group every 3 lines into one issue
    for i in range(0, len(lines), 3):
        # Join the three lines together into one string, representing the full issue
        issue_id = f"issue_{i//3 + 1}"  # Create a dynamic issue key
        lint_issues[issue_id] = " ".join(lines[i:i+3]).strip()  # Join 3 lines into a single string

    return lint_issues

def run_ansible_lint(playbook_path):
    """Runs ansible-lint and returns cleaned lint issues."""
    result = subprocess.run(['ansible-lint', playbook_path], capture_output=True, text=True)
    print(f"run_ansible_lint function - result: {result}")
    # Strip ANSI escape codes
    cleaned_output = strip_ansi_codes(result.stdout)
    #print(f"cleaned_output:\n {cleaned_output}")

    lint_issues = clean_and_group_lint_issues(cleaned_output)
    lint_issues2 = process_lint_output(cleaned_output)
    #pretty_print_yaml(lint_issues,output_file="lint1.yml")
    pretty_print_yaml(lint_issues2,output_file="lint_issues2.yml")

    return lint_issues2


def extract_line_number_from_lint_message(lint_message):
    """Extract line number from ansible-lint message using regex."""
    # Regex pattern to match line numbers (e.g., "line 61")
    match = re.search(r'(\d+)$', lint_message)
    if match:
        return int(match.group(1))
    return None

# Generates a fix suggestion using Ollama (Llama3 or Mistral).
def get_ai_fix_suggestion(lint_issue,playbook_path):
    # Extract line number from lint_issue using the new function
    line_number = extract_line_number_from_lint_message(lint_issue)
    
    if line_number is None:
        return "Error: Could not extract line number from lint message."

    # Fetch the actual line from the playbook
    line_content = get_line_from_file(playbook_path, line_number)
    
#    prompt = f"Fix this Ansible lint issue:\n{lint_issue}\nThe content of the problematic line is:\n{line_content}\nProvide a corrected version. Print the original lint issue and print line_content with title: Line Content: . On a new line print your suggestion and add title: I suggest:"
    prompt = f"Fix this Ansible lint issue:\n{lint_issue}\nThe content of the problematic line is:\n{line_content}\nProvide a corrected version. Your response should only contain the fixed yaml"

    response = ollama.chat(model="llama3.2", messages=[{"role": "user", "content": prompt}])

    # Extract the AI suggestion from the response content
    if isinstance(response.get('message'), ollama._types.Message):
        cleaned_message = response['message'].content  # Get the content from the Message object
    else:
        cleaned_message = 'Error in AI response format.'

    return cleaned_message


def apply_ai_fixes_to_playbook(playbook_path, fixes):
    """Applies AI fixes only to flagged lines while keeping the rest of the file unchanged."""
    # Read the original playbook
    for issue_key, fix_content in fixes.items():
        print(f"In apply_ai_fixes_to_playbook. fixes= {fixes}")
    with open(playbook_path, 'r') as file:
        original_lines = file.readlines()
    
    # Create a deep copy to modify without altering the original
    modified_lines = deepcopy(original_lines)
    
    # Iterate through each fix and apply it to the correct line number
    for issue_key, fix_content in fixes.items():
        # Extract the file path, line number, and fix
        match = re.search(r'(\S+:\d+)', issue_key)  # Match file path and line number
        print(f"match is: {match}")
        if match:
            file_path_and_line = match.group(0)  # e.g. 'get_stats.yml:61'
            file_path, line_num = file_path_and_line.split(':')
            line_num = int(line_num) - 1  # Convert to zero-based index
            
            # If the line number is valid, apply the fix
            if 0 <= line_num < len(modified_lines):
                modified_lines[line_num] = fix_content.strip() + "  # Fixed by AI\n"
    
    return modified_lines

def write_updated_playbook(playbook_path, updated_lines):
    """Writes the modified playbook to a new file."""
    fixed_playbook_path = playbook_path.replace('.yml', '_fixed.yml')
    with open(fixed_playbook_path, 'w') as file:
        file.writelines(updated_lines)
    return fixed_playbook_path

# Writes chat history (lint issues and AI fixes) to a separate text file.
def write_chat_output(chat_file_path, fixes):
    with open(chat_file_path, 'w') as file:
        for issue, fix in fixes.items():
            file.write(f"❌ **Lint Issue:** {issue}\n")
            file.write(f"💡 **Suggested Fix:**\n{fix}\n")
            file.write('-' * 80 + '\n')

def pretty_print_yaml(data, output_file="d1.yml"):
    """
    Pretty prints the given YAML data to a file.
    If the output file exists, it is overwritten.
    Prompts for a filename if not provided.
    """
    # If no output file is specified, prompt the user for a filename
    if not output_file:
        output_file = input(
            "Enter the output file name (including .yaml or .yml extension): "
        ).strip()

    # Generate pretty YAML string
    pretty_yaml = yaml.dump(data, sort_keys=False, default_flow_style=False, indent=4)

    # Remove existing file if it exists to ensure fresh write
    if os.path.exists(output_file):
        os.remove(output_file)
        print(f"Deleted existing file: {output_file}")

    # Attempt to write the pretty YAML to the file
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(pretty_yaml)
        print(f"Pretty-printed YAML has been written to {output_file}")
    except Exception as e:
        print(f"Error writing YAML file: {e}")

def get_line_from_file(file_path, line_number):
    """Fetch a specific line from a file based on the line number."""
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()
            if 0 < line_number <= len(lines):
                print(f"Going to return line: {lines[line_number - 1].strip()}")
                return lines[line_number - 1].strip()  # line_number is 1-indexed
            else:
                return f"Error: Line number {line_number} out of range."
    except FileNotFoundError:
        return f"Error: File '{file_path}' not found."
    except Exception as e:
        return f"Error: {str(e)}"

def lintAI_flow():
    # Main execution
    playbook_path = "redhat-amq_broker-2.2.9/roles/amq_broker/tasks/main.yml"
    lint_issues = run_ansible_lint(playbook_path)
    pretty_print_yaml(lint_issues,output_file="lint_issues.yml")
    # Collect AI-generated fixes for each lint issue
    fixes = {}
    for issue in lint_issues:
        print(f"Processing lint issue: {issue}")
        issue_value = lint_issues[issue]  # Get the actual value of the issue
        fix = get_ai_fix_suggestion(issue_value, playbook_path)  # Use the value in the AI suggestion
        print(f"Suggested Fix: {fix}")
        fixes[issue] = fix  # Store the fix in the dictionary

    print(f"fixes:{fixes}")
    
    updated_lines = apply_ai_fixes_to_playbook(playbook_path, fixes)
    fixed_playbook_path = write_updated_playbook(playbook_path, updated_lines)
    chat_file_path = playbook_path.replace('.yml', '_chat_output.txt')
    write_chat_output(chat_file_path, fixes)
    print(fixes)

    #print(f"The fixed playbook has been written to: {fixed_playbook_path}")
    print(f"The chat history has been written to: {chat_file_path}")

# Main call
if __name__ == "__main__":
    lintAI_flow()
