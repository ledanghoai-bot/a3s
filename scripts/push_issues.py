import subprocess
import re

def push_issues_to_gitlab(filename):
    with open(filename, 'r', encoding='utf-8') as file:
        content = file.read()

    # Tách file .md thành từng phần dựa trên ký tự "## "
    # Mỗi phần sẽ là một Issue
    issues = content.split('## ')
    
    for issue in issues:
        if not issue.strip():
            continue
            
        # Tách dòng đầu tiên làm Tiêu đề, các dòng còn lại làm Mô tả
        lines = issue.strip().split('\n')
        title = lines[0].strip()
        description = "\n".join(lines[1:]).strip()
        
        print(f"🚀 Đang đẩy issue: {title}...")
        
        # Sử dụng công cụ 'glab' đã login trước đó để bắn lệnh lên GitLab
        cmd = [
            'glab', 'issue', 'create',
            '-t', title,
            '-d', description
        ]
        
        # Chạy lệnh hệ thống
        # Chạy lệnh hệ thống (Mới - Đã sửa lỗi Windows)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', shell=True)
        
        if result.returncode == 0:
            print(f"✅ Thành công!")
        else:
            print(f"❌ Thất bại: {result.stderr}")

if __name__ == "__main__":
    # Đổi tên file tương ứng với file .md của bạn
    push_issues_to_gitlab('issues.md')