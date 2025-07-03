import os
import email
from email.policy import default
import logging
from tqdm import tqdm

logging.basicConfig(level=logging.INFO)


def extract_html_from_eml(eml_file_path):
    """
    从.eml文件中提取HTML内容并保存为.html文件

    :param eml_file_path: .eml文件的路径
    :param output_html_path: 输出的.html文件路径
    """
    year, month, bsname = eml_file_path.split(os.sep)
    filename, extension = os.path.splitext(bsname)
    
    # year = eml_file_path[:4]
    # filename = os.path.basename(eml_file_path).split('.')[0]
    output_html_path = os.path.join('htmls', year, filename + '.html')
    eml_file_path = os.path.join('spamfiles', eml_file_path)
    
    try:
        # 读取并解析邮件
        with open(eml_file_path, 'rb') as f:
            msg = email.message_from_bytes(f.read(), policy=default)
        
        # 提取所有HTML部分
        html_parts = []
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                # 动态处理编码
                charset = part.get_content_charset() or 'utf-8'
                try:
                    html_content = part.get_payload(decode=True).decode(charset, errors='replace')
                    html_parts.append(html_content)
                except UnicodeDecodeError:
                    logging.warning(f"解码失败（字符集：{charset}），使用替代字符。")
                    html_content = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    html_parts.append(html_content)
        
        # 保存结果
        if html_parts:
            with open(output_html_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(html_parts))
            logging.info(f"成功保存 {len(html_parts)} 个HTML部分到 {output_html_path}")
            return True
        else:
            logging.warning("未找到HTML内容")
            return False
    except FileNotFoundError:
        logging.error(f"文件不存在：{eml_file_path}")
        return False
    except PermissionError:
        logging.error("权限不足，无法读写文件")
        return False
    except Exception as e:
        logging.error(f"处理过程中发生错误：{str(e)}")
        return False
        
if __name__ == "__main__":
    extract_html_from_eml(eml_file_path)