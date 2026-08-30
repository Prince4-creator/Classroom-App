#!/usr/bin/env python3
"""
Script to automatically add CSRF tokens to all HTML templates with forms.
Adds {{ csrf_token() }} as a hidden input inside each <form> tag.
"""

import os
import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / 'templates'
CSRF_INPUT = '\n                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>'

def add_csrf_token_to_file(filepath):
    """Add CSRF token to a single HTML file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Check if file already has CSRF token
    if 'csrf_token' in content:
        return filepath, 'SKIP', 'Already has CSRF token'
    
    # Check if file has any forms
    if '<form' not in content:
        return filepath, 'SKIP', 'No forms found'
    
    # Pattern: find <form ...> and add CSRF token after it
    # Look for the first line after <form tag (usually the first input or div)
    pattern = r'(<form[^>]*>)\s*(?=\n)'
    
    def add_token(match):
        form_tag = match.group(1)
        return form_tag + CSRF_INPUT
    
    new_content = re.sub(pattern, add_token, content, flags=re.MULTILINE)
    
    # If no changes were made, try alternative pattern
    if new_content == original_content:
        # Try: <form ... > with whitespace variations
        pattern = r'(<form[^>]*>)'
        new_content = re.sub(pattern, r'\1' + CSRF_INPUT, content)
    
    # Write the updated content
    if new_content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return filepath, 'UPDATED', 'CSRF token added'
    else:
        return filepath, 'FAIL', 'Could not parse form structure'

def main():
    """Process all HTML files in templates directory."""
    print('╔════════════════════════════════════════════════════════════╗')
    print('║           CSRF TOKEN INJECTION SCRIPT                      ║')
    print('╚════════════════════════════════════════════════════════════╝')
    print()
    
    if not TEMPLATES_DIR.exists():
        print(f'ERROR: Templates directory not found: {TEMPLATES_DIR}')
        return
    
    html_files = sorted(TEMPLATES_DIR.glob('*.html'))
    
    if not html_files:
        print(f'No HTML files found in {TEMPLATES_DIR}')
        return
    
    print(f'Found {len(html_files)} HTML templates\n')
    
    results = {'UPDATED': 0, 'SKIP': 0, 'FAIL': 0}
    updates = []
    skips = []
    failures = []
    
    for filepath in html_files:
        filepath_obj, status, message = add_csrf_token_to_file(filepath)
        results[status] += 1
        
        if status == 'UPDATED':
            updates.append(filepath_obj.name)
        elif status == 'SKIP':
            skips.append((filepath_obj.name, message))
        else:
            failures.append((filepath_obj.name, message))
    
    # Print results
    print('📊 PROCESSING RESULTS:')
    print('=' * 60)
    print(f'  ✅ Updated: {results["UPDATED"]} files')
    print(f'  ⏭️  Skipped: {results["SKIP"]} files')
    print(f'  ❌ Failed:  {results["FAIL"]} files')
    print()
    
    if updates:
        print('✅ UPDATED FILES:')
        for name in updates:
            print(f'  • {name}')
        print()
    
    if skips:
        print('⏭️  SKIPPED FILES:')
        for name, msg in skips:
            print(f'  • {name} ({msg})')
        print()
    
    if failures:
        print('❌ FAILED FILES (Requires Manual Update):')
        for name, msg in failures:
            print(f'  • {name} ({msg})')
        print()
    
    print('=' * 60)
    print(f'✨ Process Complete! {results["UPDATED"]} files updated.')
    print()
    print('📝 NEXT STEPS:')
    print('  1. Review updated templates for correct CSRF placement')
    print('  2. Test all forms (login, registration, submissions)')
    print('  3. Verify CSRF protection working in browser devtools')
    print()
    print('💡 TIP: CSRF tokens are now automatically included in all forms')
    print('   and will be validated on every POST/PUT/DELETE request.')
    print()

if __name__ == '__main__':
    main()
