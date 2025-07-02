import os
import re
import shutil
import webcolors
import datetime
import json
import copy
from tqdm import tqdm
from bs4 import BeautifulSoup, Tag, Comment, Declaration, NavigableString
from collections import deque, defaultdict



# ====================== 预编译正则表达式 ======================
STYLE_PROP_RE = re.compile(r'([a-zA-Z-]+)\s*:\s*([^;]+)', re.IGNORECASE)
COLOR_HEX_RE = re.compile(r'^#([0-9a-f]{3,8})$', re.IGNORECASE)
RGB_RE = re.compile(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,?\s*([\d.]+)?\s*\)', re.IGNORECASE)
HSL_RE = re.compile(r'hsla?\(\s*(\d+)\s*,\s*(\d+)%\s*,\s*(\d+)%\s*,?\s*([\d.]+)?\s*\)', re.IGNORECASE)
LENGTH_RE = re.compile(r'([-+]?[\d.]+)(px|pt|em|rem|%)?')

# 新增正则表达式
CONDITIONAL_START_RE = re.compile(r'<!$$if\s+([^>]+)$$>', re.IGNORECASE)

CONDITIONAL_END_RE = re.compile(
    r'<!$$endif$$>',
    re.IGNORECASE
)

# 新增正则表达式处理分体式注释
SPLIT_CONDITIONAL_RE = re.compile(
    r'<!$$if\s+([^>]+)$$>([\s\S]*?)<!$$endif$$>',
    re.IGNORECASE
)

# ====================== 常量定义 ======================
INHERITABLE_PROPS = {
    'color', 'font-family', 'font-size', 'font-weight', 
    'font-style', 'line-height', 'text-indent', 'visibility',
    'opacity', 'background-color', 'bgcolor'
} # 放进这个集合里的属性才会被继承

DEFAULT_STYLE = {
    'color': {'rgb': (0, 0, 0), 'alpha': 1.0},
    'background-color': {'rgb': (255, 255, 255), 'alpha': 1.0},
    'font-size': '16px',
    'opacity': '1'
}


EXCLUDED_TAGS = {'script', 'style', 'meta', 'link', 'noscript', 'svg', 'img', 'title'}

NON_STYLABLE_TAGS = EXCLUDED_TAGS | {'br', 'hr', 'img', 'meta', 'link'}

# ====================== DOM 分析器 ======================
class DOMAnalyzer:
    def __init__(self, html_content):
        # self.soup = BeautifulSoup(html_content, 'html.parser')
        self.soup = self._handle_split_conditionals(html_content)        
        self._prune_tree()  # 新增预处理步骤
        self.paths = []
    
    # ====================== 预处理 ======================
    
    def _prune_tree(self):
        """预处理DOM树"""
        body = self.soup.find('body') or self.soup
        self._prune_empty_nodes(body)
    
    def _handle_split_conditionals(self, content):
        """处理分体式条件注释"""
        # 阶段1：合并同一条件的分体式注释
        condition_map = defaultdict(list)
        
        # 识别所有条件块
        matches = SPLIT_CONDITIONAL_RE.finditer(content)
        for match in matches:
            condition = match.group(1).strip()
            html_fragment = match.group(2)
            condition_map[condition].append(html_fragment)
        
        # 生成替换内容
        replacements = []
        for cond, fragments in condition_map.items():
            if len(fragments) > 1:
                # 合并分体片段
                merged_html = f'<!--[cond:{cond}]-->{"".join(fragments)}<!--[endcond]-->'
                for f in fragments:
                    pattern = re.escape(f'<![if {cond}]>{f}<!$$endif$$>')
                    replacements.append((pattern, merged_html))
        
        # 执行批量替换
        for pattern, replacement in replacements:
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        
        # 阶段2：常规注释处理
        return BeautifulSoup(content, 'html.parser')
        
    def _preprocess_conditional_comments(self, content):
        """预处理条件注释中的HTML内容"""
        # 阶段1：标准化条件注释标记
        content = CONDITIONAL_START_RE.sub(
            r'<!--[cond_begin:\1]-->',
            content
        )
        content = CONDITIONAL_END_RE.sub(
            '<!--[cond_end]-->',
            content
        )
        
        # 阶段2：构建文档树并处理嵌套结构
        soup = BeautifulSoup(content, 'html.parser')
        stack = []
        
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            text = comment.strip()
            if text.startswith('[cond_begin:'):
                # 解析条件表达式
                condition = text[12:-3].strip()
                # 创建虚拟容器
                container = soup.new_tag("div", **{
                    'class': 'conditional-container',
                    'data-condition': condition
                })
                # 替换注释节点
                comment.replace_with(container)
                stack.append(container)
            elif text == '[cond_end]':
                if stack:
                    container = stack.pop()
                    # 关闭当前容器
                    comment.decompose()
                    # 处理嵌套情况
                    if stack:
                        stack[-1].append(container)
            else:
                # 普通注释处理
                pass
                
        return soup
        
        
    def _process_comments(self):
        """改进的注释处理方法"""
        results = []
        
        # 处理合并后的条件注释
        for comment in self.soup.find_all(string=lambda t: isinstance(t, Comment)):
            text = comment.strip()
            
            # 处理合并后的条件块
            if text.startswith('[cond:'):
                condition = text[6:-3].strip()
                parent = comment.parent
                if parent and parent.name == 'div' and 'conditional-container' in parent.get('class', []):
                    analyzer = DOMAnalyzer(str(parent))
                    analyzer.collect_paths()
                    elements, _ = analyzer.analyze_paths()
                    
                    results.extend({
                        **elem,
                        "type": "conditional_comment",
                        # "condition": condition,
                        "visible": False,
                        # "hidden_reasons": ["split_conditional"] + elem.get("hidden_reasons", [])
                    } for elem in elements)
            
            # 原有普通注释处理
            else:
                results.append({
                    "text": text,
                    "type": "html_comment",
                    "visible": False,
                    # "hidden_reasons": ["html_comment"]
                })
        
        return results


    def _get_comment_path(self, comment):
        """获取注释节点的层级路径"""
        path = []
        parent = comment.parent
        while parent and parent.name:
            if parent.name.startswith('!'):  # 处理条件注释伪节点
                path.insert(0, parent.name.replace('!', '').split()[0])
            else:
                path.insert(0, parent.name)
            parent = parent.parent
        return path
    
    # ====================== 路径处理 ======================
    
    def _is_leaf(self, node):
        """增强版叶子节点判定"""
        if not isinstance(node, Tag):
            return False
        
        # 条件1：节点自身有直接文本
        has_self_text = any(
            isinstance(c, str) and c.strip()
            for c in node.contents
            if not isinstance(c, Tag)
        )
        
        # 条件2：所有子节点都是不可设置样式的标签
        all_children_unstylable = all(
            isinstance(c, Tag) and 
            c.name in NON_STYLABLE_TAGS 
            for c in node.children
        )
        
        # 条件3：节点本身或子节点包含可继承样式的标签
        has_stylable_descendant = any(
            isinstance(c, Tag) and 
            c.name not in NON_STYLABLE_TAGS 
            for c in node.descendants
        )
        
        return has_self_text or (all_children_unstylable and not has_stylable_descendant)
    
    def _is_empty_tag(self, tag):
        """判断是否为无内容的空标签"""
        return len(tag.contents) == 0
    
    def _is_valid_node(self, node):
        """判断节点是否有效（需处理的标签）"""
        return (
            isinstance(node, Tag) and 
            node.name not in NON_STYLABLE_TAGS and
            not isinstance(node, (Comment, Declaration))
        )
    
    def _process_anchor_tag(self, node, inherited_style):
        """专门处理<a>标签"""
        text = self._get_link_text(node)
        if not text:
            return None
        
        # 解析链接样式
        link_style = self._parse_node_style(node, inherited_style)
        visible, reasons = self._check_visibility(link_style)
        
        return {
            "text": text,
            "type": "link",
            "url": node.get('href', ''),
            # "path": [n.name for n in self._get_tag_path(node)],
            "style": link_style,
            "visible": visible,
            "hidden_reasons": reasons if not visible else []
        }

    def _get_link_text(self, node):
        """获取链接文本（包含所有子文本）"""
        return ' '.join(node.stripped_strings)

    def _get_tag_path(self, node):
        """获取单个标签的独立路径"""
        path = []
        while node and node.name:
            path.insert(0, node.name)
            node = node.parent
        return path

    def _has_loose_text(self, node):
        """检测节点是否包含游离文本（直接文本内容）"""
        return any(
            isinstance(child, str) and child.strip()
            for child in node.contents
            if not isinstance(child, Tag)
        )
        
    def _prune_empty_nodes(self, node):
        """后序遍历剪枝空节点"""
        if not isinstance(node, Tag):
            return False
        
        # 递归处理子节点
        for child in list(node.children):  # 转换为list避免遍历时修改
            if self._prune_empty_nodes(child):
                child.decompose()  # 移除空子节点
        
        # 判断当前节点是否为空
        is_empty = (
            not self._has_any_text(node) and
            not self._has_meaningful_children(node)
        )
        return is_empty

    def _has_any_text(self, node):
        """检查节点或后代是否存在有效文本"""
        return any(
            isinstance(c, str) and c.strip()
            for c in node.stripped_strings
        )

    def _has_meaningful_children(self, node):
        """检查是否有有效子节点"""
        return any(
            self._is_valid_node(child) 
            for child in node.children
            if isinstance(child, Tag)
        )

    def collect_paths(self):
        """优化后的路径收集"""
        root = self.soup.find('body') or self.soup
        queue = deque([(root, tuple())])
        
        while queue:
            node, path = queue.popleft()
            # 跳过注释节点和非标签节点
            if not isinstance(node, Tag) or isinstance(node, (Comment, Declaration)):
                continue
            
            if not self._is_valid_node(node):  # 使用新方法验证
                continue
                
            new_path = path + (node,)
            
            if self._is_leaf(node):
                self.paths.append(new_path)
                continue
                
            # 添加有效子节点
            for child in node.children:
                if self._is_valid_node(child):
                    queue.append((child, new_path))
                    
    def analyze_paths(self):
        """处理所有路径的样式继承"""
        results = []
        file_visible = True
        
        for path in self.paths:
            inherited_style = copy.deepcopy(DEFAULT_STYLE)
            
            for node in path:
                # ========== 新增 <a> 标签处理逻辑 ==========
                if node.name == 'a':
                    link_result = self._process_anchor_tag(node, inherited_style)
                    if link_result:
                        results.append(link_result)
                    # 跳过后续子节点处理
                    break
                # ========== 原有样式处理逻辑 ==========
                current_style = self._parse_node_style(node, inherited_style)
                text_content = self._get_node_text(node)
                
                if text_content:
                    visible, reasons = self._check_visibility(current_style)
                    if not visible:
                        file_visible = False
                    results.append({
                        "text": text_content,
                        "type": "text",  # 新增文本类型标识
                        # "path": [n.name for n in path],
                        "style": current_style,
                        "visible": visible,
                        "hidden_reasons": reasons if not visible else []
                    })
                
                # 准备继承属性
                inherited_style = {
                    k: copy.deepcopy(v) 
                    for k, v in current_style.items()
                    if k in INHERITABLE_PROPS
                }
                
        results.extend(self._process_comments())
        return results, file_visible

    # ====================== 样式解析 ======================
    def _parse_opacity(self, current_value, parent_opacity='1'):
        """
        解析透明度值并计算累积透明度
        参数:
            current_value (str): 当前元素的opacity值 (如 "0.5" 或 "50%")
            parent_opacity (str): 父元素的opacity值 (默认 '1')
        返回:
            str: 计算后的累积透明度字符串
        """
        # 解析父元素透明度
        try:
            parent_alpha = float(parent_opacity)
        except:
            parent_alpha = 1.0

        # 解析当前元素透明度
        try:
            # 去除空格并处理百分号
            value = current_value.strip().replace('%', '')
            current_alpha = float(value)
            
            # 处理百分比值
            if '%' in current_value:
                current_alpha /= 100.0
                
            # 限制数值范围
            current_alpha = max(0.0, min(1.0, current_alpha))
        except:
            current_alpha = 1.0

        # 计算累积透明度
        combined_alpha = parent_alpha * current_alpha
        return f"{combined_alpha:.2f}"

    def _parse_node_style(self, node, inherited_style):
        """解析节点样式（包含继承处理）"""
        # 深拷贝继承样式
        style = copy.deepcopy(inherited_style)
        
        # 处理元素opacity属性
        current_opacity = self._parse_opacity(
            node.get('opacity', '1'), 
            inherited_style.get('opacity', '1.0')
        )
        
        # 处理特殊标签属性
        if node.name == 'font':
            attrs = {k.lower(): v for k, v in node.attrs.items()}
            if 'color' in attrs:
                style['color'] = self._parse_color(attrs['color'])
                current_opacity = self._parse_opacity(style['color']['alpha'], current_opacity)
                
            if 'size' in attrs:
                style['font-size'] = self._parse_font_size(attrs['size'])
                
        # ========== 新增通用 bgcolor 处理逻辑 ==========
        if node.name in ('table', 'tr', 'td', 'th', 'font', 'body'):
            # 处理背景颜色
            attrs = {k.lower(): v for k, v in node.attrs.items()}
            if 'bgcolor' in attrs:
                parsed_color = self._parse_color(attrs['bgcolor'], 'bg')
                # 混合当前背景色与已存在的背景色（处理嵌套情况）
                if 'background-color' in style:
                    existing_bg = copy.deepcopy(style['background-color'])
                    new_bg = self._blend_colors(parsed_color, existing_bg)
                    style['background-color'] = new_bg
                else:
                    style['background-color'] = parsed_color
            if 'text' in attrs:
                style['color'] = self._parse_color(attrs['text'])
                current_opacity = self._parse_opacity(style['color']['alpha'], current_opacity)
            
            # 处理对齐方式
            if 'align' in attrs:
                align_map = {
                    'left': 'left',
                    'right': 'right',
                    'center': 'center',
                    'middle': 'center',
                    'justify': 'justify'
                }
                style['text-align'] = align_map.get(attrs['align'].lower(), 'left')
            
            # 处理宽度（自动补充单位）
            if 'width' in attrs:
                width = attrs['width']
                if re.match(r'^\d+$', width):  # 纯数字自动添加px
                    style['width'] = f"{width}px"
                else:
                    style['width'] = width  # 保留带单位的值
        # ========== 表格属性处理结束 ==========
        
        # 解析内联样式
        if 'style' in node.attrs:
            inline_style = dict(STYLE_PROP_RE.findall(node['style']))
            for prop, value in inline_style.items():
                prop = prop.lower()
                if prop in ['background-color', 'bgcolor']:
                    style['background-color'] = self._parse_color(value, 'bg')
                elif prop == 'color':
                    style[prop] = self._parse_color(value)
                    current_opacity = self._parse_opacity(style['color']['alpha'], current_opacity)
                elif prop == 'font-size':
                    style[prop] = self._parse_font_size(value)
                elif prop == 'opacity':
                    # 修改此处调用方式
                    current_opacity = self._parse_opacity(value, current_opacity)
                else:
                    style[prop] = value
        
        # 计算累积透明度
        style['opacity'] = current_opacity
        # style['opacity'] = self._calculate_opacity(style)
        return style

    # ====================== 可见性检查 ======================
    def _check_visibility(self, style):
        """综合可见性检测"""
        reasons = []
        
        # 基础属性检测
        if style.get('visibility') in ('hidden', 'collapse'):
            reasons.append('不可见控制:visibility')
        if style.get('display') == 'none':
            reasons.append('不可见控制:display:none')
        
        # 透明度检测
        if float(style.get('opacity', 1)) <= 0.01:
            reasons.append(f'透明度: opacity:{style["opacity"]}')
        
        # 修正对比度检测逻辑
        final_fg = self._parse_color(style['color'])
        bg = self._parse_color(style.get('background-color'), 'bg')
        
        # 递归混合得到实际显示颜色
        final_bg = self._parse_color(self._blend_colors(bg, DEFAULT_STYLE['background-color']))
        
        # 计算最终对比度
        contrast = self._calculate_contrast(final_fg, final_bg)
        
        if final_fg == final_bg:
            reasons.append('颜色相同: same_color')
        elif contrast < 1.05:
            reasons.append(f'对比度: low_contrast({contrast})')
        
        
        # 位置偏移检测
        if self._check_position_offset(style):
            reasons.append('位置偏移: position_offset')
        
        # 剪切检测
        if self._check_clipping(style):
            reasons.append('剪切区域: clipping')
        
        # 字体尺寸检测
        font_size = self._parse_length(style.get('font-size', '16px'))
        if font_size < 3:  # 从1px调整为6px
            reasons.append(f'字体过小: {font_size}px')
        
        # 滤镜检测
        if self._check_filter(style):
            reasons.append('滤镜: filter_effect')
        
        return (len(reasons) == 0, reasons)

    def _check_position_offset(self, style):
        """位置偏移检测"""
        offset_props = {
            'left', 'right', 'top', 'bottom',
            'margin-left', 'margin-right',
            'margin-top', 'margin-bottom',
            'text-indent'
        }
        return any(
            self._is_large_offset(style.get(prop, '0'))
            for prop in offset_props
        )

    def _check_clipping(self, style):
        """剪切区域检测"""
        return any(
            prop in style and self._is_hidden_clip(style[prop])
            for prop in ['clip-path', 'clip']
        )

    def _check_font_size(self, style):
        """字体尺寸检测"""
        font_size = self._parse_length(style.get('font-size', '16px'))
        return font_size and font_size < 1  # <1px视为隐藏

    def _check_filter(self, style):
        """滤镜效果检测"""
        if 'filter' not in style:
            return False
        return any(
            self._is_hiding_filter(f)
            for f in style['filter'].split()
        )

    # ====================== 辅助方法 ======================
    def _parse_length(self, value, base_size=16):
        """解析CSS长度值为像素"""
        match = LENGTH_RE.match(str(value))
        if not match:
            return None
            
        num, unit = match.groups()
        num = float(num)
        
        if unit == 'pt':
            return num * 1.333
        if unit == 'em':
            return num * base_size
        if unit == 'rem':
            return num * 16  # 假设根字体16px
        if unit == '%':
            return num / 100 * base_size
        return num  # px单位或无单位

    def _is_large_offset(self, value, threshold=1000):
        """判断是否为大的偏移值"""
        parsed = self._parse_length(value)
        return parsed and abs(parsed) > threshold

    def _is_hidden_clip(self, value):
        """判断剪切值是否隐藏内容"""
        value = value.lower()
        return any(
            pattern in value
            for pattern in ['inset(100%', 'rect(0', 'circle(0', 'polygon(0 0']
        )

    def _is_hiding_filter(self, filter_func):
        """判断滤镜是否导致隐藏"""
        filter_func = filter_func.lower()
        if filter_func.startswith('opacity('):
            return float(filter_func[7:-1].strip('%')) <= 5
        if filter_func.startswith('blur('):
            blur_val = filter_func[5:-1]
            return self._parse_length(blur_val) > 10  # >10px模糊
        return False

    def _calculate_opacity(self, style):
        """计算累积透明度"""
        current_opacity = float(style.get('opacity', 1.0))
        return str(current_opacity)

    
    # ====================== 颜色处理 ======================
    def _parse_color(self, value, colortype = 'fg'):
        """支持多种输入格式的颜色解析方法"""
        # 类型分流处理
        try:
            if isinstance(value, str):
                return self._parse_color_string(value)
            elif isinstance(value, tuple):
                return self._parse_color_tuple(value)
            elif isinstance(value, list):
                return self._parse_color_tuple(tuple(value))
            else:
                return self._parse_color_dict(value)
        except:    
            
            if colortype == 'fg': # 未知类型返回字体默认黑色
                return {'rgb': (0, 0, 0), 'alpha': 1.0}
            else: # 未知类型返回背景默认白色
                return {'rgb': (255, 255, 255), 'alpha': 1.0}
    
    
    
    def _parse_color_string(self, value):
        """支持Alpha通道的增强颜色解析"""
        value = value.strip().lower()
        
        # 处理透明色
        if value == 'transparent':
            return {'rgb': (0, 0, 0), 'alpha': 0.0}
        
        # 十六进制格式
        if hex_match := COLOR_HEX_RE.match(value):
            hex_val = hex_match.group(1)
            
            # 扩展简写格式
            if len(hex_val) in (3, 4):
                hex_val = ''.join(c*2 for c in hex_val)
            
            # 解析RGB和Alpha通道
            rgb_part = hex_val[:6]
            alpha_hex = hex_val[6:] if len(hex_val) > 6 else ''
            # 处理不足两位的情况，默认ff（不透明）
            alpha_hex = (alpha_hex + 'ff')[:2]
            alpha = int(alpha_hex, 16) / 255.0
            
            return {
                'rgb': (
                    int(rgb_part[0:2], 16),
                    int(rgb_part[2:4], 16),
                    int(rgb_part[4:6], 16)
                ),
                'alpha': alpha
            }
            
        # RGB/RGBA格式
        if rgb_match := RGB_RE.match(value):
            r, g, b = map(int, rgb_match.groups()[:3])
            alpha = float(rgb_match.group(4) or 1)
            return {
                'rgb': (r, g, b),
                'alpha': alpha  # 修正变量名
            }
        
        # HSL/HSLA格式
        if hsl_match := HSL_RE.match(value):
            h = int(hsl_match.group(1))
            s = int(hsl_match.group(2).replace('%', ''))
            l = int(hsl_match.group(3).replace('%', ''))
            alpha = float(hsl_match.group(4) or 1)
            return self._hsl_to_rgb(h, s, l, alpha)
        
        
        r, g, b = webcolors.name_to_rgb(value)
        return {'rgb': (r, g, b), 'alpha': 1.0}
        
        
    def _parse_color_tuple(self, value_tuple):
        """处理元组类型的颜色值"""
        # 格式验证
        if len(value_tuple) not in (3, 4):
            return {'rgb': (0, 0, 0), 'alpha': 1.0}
        
        # 提取RGB和Alpha
        r, g, b = value_tuple[:3]
        alpha = value_tuple[3] if len(value_tuple) == 4 else 1.0
        
        # 数值范围检查
        def clamp(x):
            return max(0, min(x, 255))
        
        return {
            'rgb': (clamp(r), clamp(g), clamp(b)),
            'alpha': max(0.0, min(alpha, 1.0))
        }

    def _parse_color_dict(self, value_dict):
        """处理字典类型的颜色值"""
        # 字段验证
        required_keys = {'rgb', 'alpha'}
        if not all(k in value_dict for k in required_keys):
            return {'rgb': (0, 0, 0), 'alpha': 1.0}
        
        # 深度拷贝防止污染原始数据
        return {
            'rgb': tuple(value_dict['rgb']),
            'alpha': float(value_dict['alpha'])
        }

    def _hsl_to_hex(self, h, s, l, alpha=1.0):
        """HSL转十六进制"""
        h /= 360.0
        s /= 100.0
        l /= 100.0
        
        if s == 0:
            r = g = b = l
        else:
            def hue_to_rgb(p, q, t):
                t += 1 if t < 0 else 0
                t -= 1 if t > 1 else 0
                if t < 1/6: return p + (q - p) * 6 * t
                if t < 1/2: return q
                if t < 2/3: return p + (q - p) * (2/3 - t) * 6
                return p
            
            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue_to_rgb(p, q, h + 1/3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h - 1/3)
        
        r, g, b = (int(round(x*255)) for x in (r, g, b))
        return f'#{r:02x}{g:02x}{b:02x}' + (f'{int(alpha*255):02x}' if alpha < 1 else '')
    
    def _hsl_to_rgb(self, h, s, l, alpha=1.0):
        """HSL转十六进制"""
        h /= 360.0
        s /= 100.0
        l /= 100.0
        
        if s == 0:
            r = g = b = l
        else:
            def hue_to_rgb(p, q, t):
                t += 1 if t < 0 else 0
                t -= 1 if t > 1 else 0
                if t < 1/6: return p + (q - p) * 6 * t
                if t < 1/2: return q
                if t < 2/3: return p + (q - p) * (2/3 - t) * 6
                return p
            
            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue_to_rgb(p, q, h + 1/3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h - 1/3)
        
        r, g, b = (int(round(x*255)) for x in (r, g, b))
        return {
            'rgb': (r, g, b),  # 整型元组(0-255)
            'alpha': alpha         # 浮点数(0.0-1.0)
        }
    
    def _blend_colors(self, fg, bg):
        """递归混合颜色直到不透明"""
        # 类型检查与转换
        # print(f"混合颜色：前景色 {fg}，背景色 {bg}")
        
        fg = self._parse_color(fg) if not isinstance(fg, dict) else fg
        bg = self._parse_color(bg, 'bg') if not isinstance(bg, dict) else bg
        
        # 处理完全透明的情况
        alpha = fg['alpha'] + bg['alpha'] * (1 - fg['alpha'])
        if fg['alpha'] == 0:
            return {'rgb': (0, 0, 0), 'alpha': 0.0}

        # 混合公式：result = fg * fg.alpha + bg * (1 - fg.alpha)
        blended_rgb = [
            int(min(255, fg['rgb'][i] * fg['alpha'] + bg['rgb'][i] * bg['alpha'] * (1 - fg['alpha'])))
            for i in range(3)
        ]
        blended_alpha = fg['alpha'] + bg['alpha'] * (1 - fg['alpha'])
        
        return {
            'rgb': tuple(blended_rgb),
            'alpha': blended_alpha
        }

    def _parse_font_size(self, value):
        """字体大小解析器"""
        value = str(value).strip().lower()
        
        # 传统字号 (1-7)
        if value.isdigit() and 1 <= int(value) <= 7:
            sizes = {1:10, 2:13, 3:16, 4:18, 5:24, 6:32, 7:48}
            return f"{sizes[int(value)]}px"
        
        # 现代单位
        if match := re.match(r'^([\d.]+)(px|pt|em|%)$', value):
            num, unit = match.groups()
            num = float(num)
            if unit == 'pt':
                return f"{round(num * 1.333)}px"
            return f"{num}{unit}"
        
        return '16px'
    
    def _normalize_color(self, color):
        """颜色标准化为RGBA元组"""
        try:
            if color.startswith('rgba'):
                r, g, b, a = map(float, color[5:-1].split(','))
                return (int(r), int(g), int(b), a)
            return webcolors.hex_to_rgb(color) + (1.0,)
        except:
            return (0, 0, 0, 1.0)

    def _calculate_contrast(self, fg, bg):
        """WCAG 2.1标准对比度计算"""
        def linearize(c):
            c /= 255.0
            return c/12.92 if c <= 0.03928 else ((c + 0.055)/1.055)**2.4
        
        
        # # 混合最终显示颜色
        # final_fg = self._blend_colors(fg, bg)
        # final_bg = self._blend_colors(bg, DEFAULT_STYLE['background-color'])
        
        # 计算相对亮度（去除额外0.05）
        l1 = sum(coeff * linearize(c) for coeff, c in zip([0.2126, 0.7152, 0.0722], fg['rgb']))
        l2 = sum(coeff * linearize(c) for coeff, c in zip([0.2126, 0.7152, 0.0722], bg['rgb']))

        # 正确应用对比度公式
        l1 += 0.05
        l2 += 0.05
        return round(max(l1, l2) / min(l1, l2), 2)

    # ====================== 其他工具方法 ======================
    def _get_node_text(self, node):
        """智能文本收集方法"""
        # 情况1：子节点无可见性相关样式 → 合并全部文本
        # if not self._children_have_visibility_style(node):
        #     return node.get_text(" ", strip=True)
        
        # 情况2：存在样式控制 → 仅收集直接文本
        texts = []
        for child in node.children:
            # 处理普通文本节点（排除注释/声明）
            if isinstance(child, NavigableString) and not isinstance(child, (Comment, Declaration)):
                stripped = child.strip()
                if stripped:
                    texts.append(stripped)
            # 注意：不处理 Tag 类型节点，它们由路径收集器递归处理
        return ' '.join(texts).strip()
        

    def _children_have_visibility_style(self, node):
        """精准检测影响文本可见性的样式（递归深度优先）"""
        VISIBILITY_PROPS = {
            # 颜色与背景
            'color', 'background-color', 'background', 'bgcolor',
            # 字体与文本
            'font', 'font-size', 'font-family', 'font-weight', 'font-style',
            'line-height', 'letter-spacing', 'text-indent', 'text-shadow',
            # 显示控制
            'display', 'visibility', 'opacity', 'filter', 
            # 布局隐藏
            'position', 'top', 'left', 'right', 'bottom', 
            'clip', 'clip-path', 'overflow', 'transform',
            # 混合模式
            'mix-blend-mode', 'isolation',
            # 特殊效果
            'box-shadow', 'backdrop-filter',
            # 实验性属性
            'contain', 'will-change'
        }
        
        for child in node.children:
            if not isinstance(child, Tag):
                continue
                
            # 检查内联样式
            if 'style' in child.attrs:
                # 提取所有样式属性（不区分大小写）
                style_props = {k.lower() for k, _ in STYLE_PROP_RE.findall(child['style'])}
                if style_props & VISIBILITY_PROPS:
                    return True
                    
            # 检查HTML原生属性
            if self._check_html_visibility_attrs(child):
                return True
                
            # 递归检测子节点（深度优先）
            if self._children_have_visibility_style(child):
                return True
                
        return False

    def _check_html_visibility_attrs(self, node):
        """检测HTML原生可见性相关属性"""
        attrs = {k.lower(): v for k, v in node.attrs.items()}
        
        # 通用属性检测
        if 'hidden' in attrs:
            return True
        if 'bgcolor' in attrs and attrs['bgcolor'] != 'transparent':
            return True
            
        # 标签特有属性
        tag = node.name.lower()
        if tag == 'font' and any(a in attrs for a in ['color', 'size']):
            return True
        if tag == 'marquee' and 'behavior' in attrs:
            return True
        if tag in ('table', 'td', 'th') and 'background' in attrs:
            return True
            
        # 过时但仍在使用的属性
        if any(attrs.get(a) for a in ['noshade', 'nowrap']):
            return True
            
        return False
    
# ====================== 文件处理函数 ======================
def process_html_file(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        
        try:
            analyzer = DOMAnalyzer(f.read())
            # print(f"Processing: {os.path.basename(input_path)}")
            analyzer.collect_paths()
            # print(f"有效路径数: {len(analyzer.paths)}")
            results, file_visible = analyzer.analyze_paths()
            with open(output_path, 'a', encoding='utf-8') as f:
                for res in results:
                    f.write(json.dumps(res)+"\n")
        
            if file_visible:
                write_log(f"{input_path}\tTEXT_ALL_VISIBLE")
            else:
                shutil.copy2(input_path, 'invisible_htmls')
                shutil.copy2(output_path, 'invisible_jsons')
                write_log(f"{input_path}\tFOUND_INVISIBLE")
            
        except Exception as e:
            print(f"{input_path}处理出错,\n 错误原因{e}")
    
    
    
    

def get_already_files(log_file):
    print(f'{str(datetime.datetime.now())}\t查询已处理过的文件列表')
    already_files = []
    
    if not os.path.exists(log_file):
        with open("html_invisible_log.txt", 'w') as f:
            pass
    
    with open(log_file, 'r') as f:
        for line in f.readlines():
            already_files.append(line.split('\t')[0])
    
    print(f'{str(datetime.datetime.now())}\t已处理文件[{len(already_files)}]个')
    
    return already_files
    
def write_log(msg):
    with open("html_invisible_log.txt", 'a', encoding='utf-8') as f:
        f.write(msg + '\n')



# ====================== 主程序 ======================

if __name__ == '__main__':
    
    command = 'test'
    
    if command == 'run':
        OUTPUT_DIR = 'text_analysis'
        already_files = get_already_files("html_invisible_log.txt")
        
        for i in range(2023, 2025):
            year = str(i)
            
            if not os.path.exists(os.path.join('text_analysis', year)):
                os.makedirs(os.path.join('text_analysis', year))
        
            INPUT_DIR = 'htmls' + "/" + year
        
            for filename in tqdm(os.listdir(INPUT_DIR), desc=f"正在检测{year}的可见性"):
                if filename.endswith('.html'):
                    basename, extension = os.path.splitext(filename)
                    input_path = os.path.join(INPUT_DIR, filename)
                    if input_path in already_files:
                        print("已经检测过, 跳过")
                        continue
                    
                    output_path = os.path.join(OUTPUT_DIR, year, f"{basename}.json")
                    process_html_file(input_path, output_path)
        # ====================== 主程序结束 ======================            
    else:

    # # ====================== 测试程序 ======================
        
        INPUT_DIR = "test_html"
        OUTPUT_DIR = "test_html"
        
        for filename in tqdm(os.listdir(INPUT_DIR), desc=f"[TESTING] 正在进行测试..."):
            if filename.endswith('.html'):
                basename, extension = os.path.splitext(filename)
                input_path = os.path.join(INPUT_DIR, filename)
                output_path = os.path.join(OUTPUT_DIR, f"{basename}.json")
                process_html_file(input_path, output_path)

