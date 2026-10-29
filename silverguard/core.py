"""Evidence-first parser and deterministic risk rules. No account access."""
import re
from decimal import Decimal

SERVICES = {
    # Existing services
    '爱奇艺':'视频', '腾讯视频':'视频', '优酷':'视频', '芒果TV':'视频',
    'QQ音乐':'音乐', '网易云':'音乐', '酷狗':'音乐',
    '淘宝省钱卡':'购物', '淘宝':'购物', '京东':'购物', '拼多多':'购物',
    '中国移动':'手机服务', '中国联通':'手机服务', '中国电信':'手机服务',
    '云存储':'软件订阅', '办公软件':'软件订阅', '游戏充值':'游戏充值',

    # Video and streaming
    '哔哩哔哩':'视频', 'B站':'视频', '抖音':'视频', '快手':'视频',
    '咪咕视频':'视频', '搜狐视频':'视频', '西瓜视频':'视频',
    '爱奇艺会员':'视频', '腾讯视频VIP':'视频', '优酷会员':'视频',
    '芒果TV会员':'视频', 'Netflix':'视频', 'Disney+':'视频',
    'Prime Video':'视频', 'YouTube Premium':'视频',

    # Music and audio
    '网易云音乐':'音乐', 'QQ音乐绿钻':'音乐', '酷我音乐':'音乐',
    '汽水音乐':'音乐', 'Apple Music':'音乐', 'Spotify':'音乐',
    'YouTube Music':'音乐', '咪咕音乐':'音乐',
    '喜马拉雅':'有声内容', '懒人听书':'有声内容',

    # Reading and knowledge services
    '微信读书':'阅读', '起点读书':'阅读', '番茄小说':'阅读',
    '七猫小说':'阅读', '掌阅':'阅读', '晋江文学城':'阅读',
    '豆瓣阅读':'阅读', '知乎盐选':'知识服务',

    # Shopping memberships
    '淘宝88VIP':'购物会员', '京东PLUS':'购物会员',
    '拼多多省钱月卡':'购物会员', '美团省钱卡':'购物会员',
    '山姆会员':'购物会员', '盒马X会员':'购物会员',

    # Telecom and cloud storage
    '中国移动云盘':'云存储', '和彩云':'云存储',
    '中国联通沃云':'云存储', '天翼云盘':'云存储',
    '百度网盘':'云存储', '夸克网盘':'云存储', '阿里云盘':'云存储',
    '腾讯微云':'云存储', 'iCloud+':'云存储', 'iCloud':'云存储',
    'OneDrive':'云存储', 'Google One':'云存储', 'Dropbox':'云存储',
    '坚果云':'云存储',

    # Productivity and design tools
    'WPS会员':'办公软件', 'Microsoft 365':'办公软件',
    'Office 365':'办公软件', '金山文档':'办公软件',
    '腾讯文档':'办公软件', '石墨文档':'办公软件', '飞书':'办公软件',
    '钉钉':'办公软件', '印象笔记':'办公软件', 'Evernote':'办公软件',
    'Notion':'办公软件', '语雀':'办公软件', '幕布':'办公软件',
    'Adobe Creative Cloud':'设计软件', 'Canva Pro':'设计软件',

    # AI and developer tools
    'ChatGPT Plus':'AI服务', 'ChatGPT Pro':'AI服务', 'Claude Pro':'AI服务',
    'Perplexity Pro':'AI服务', 'Midjourney':'AI服务', 'Cursor':'开发工具',
    'GitHub Copilot':'开发工具', '通义千问会员':'AI服务',
    '文心一言会员':'AI服务', '讯飞星火':'AI服务',

    # Games and game subscriptions
    'Steam':'游戏服务', 'PlayStation Plus':'游戏服务',
    'Xbox Game Pass':'游戏服务', 'Nintendo Switch Online':'游戏服务',
    '原神':'游戏服务', '王者荣耀':'游戏服务', '和平精英':'游戏服务',
    '崩坏：星穹铁道':'游戏服务', '崩坏星穹铁道':'游戏服务',
    '米哈游':'游戏服务', '腾讯游戏':'游戏服务', '网易游戏':'游戏服务',
    'TapTap':'游戏服务',

    # Food delivery, transport and travel
    '美团外卖':'生活服务', '饿了么':'生活服务',
    '滴滴出行':'出行服务', '曹操出行':'出行服务',
    '高德打车':'出行服务', '哈啰':'出行服务',
    '携程':'旅行服务', '同程旅行':'旅行服务', '飞猪':'旅行服务',

    # Fitness and education
    'Apple Fitness+':'健身服务', '薄荷健康':'健康服务',
    '学而思':'教育服务', '猿辅导':'教育服务', '作业帮':'教育服务',
    '中国大学MOOC':'教育服务', 'Coursera':'教育服务',
}
ADVICE = {
    'verify': '先打开您平时使用的官方 App，核对服务名称、金额和扣费日期。不要从陌生短信链接进入。',
    'renew': '如果不再需要，请在官方 App 内搜索“自动续费”或“自动扣款”，查看这个服务的管理说明。',
    'cancel': '只有看到官方页面显示关闭成功，才算关闭了自动续费。卸载 App 通常不等于关闭续费。',
    'contact': '仍不认识这笔钱时，请从官方 App 的帮助入口联系人工客服，也可以请信任的家人一起核对。',
    'trial': '在官方服务页面查看试用到期日、之后的价格和关闭方式。',
    'phishing': '先不要点击短信链接、转账或提供验证码。请自行打开官方 App 核实。',
    'paid': '这份信息显示已经关闭或未开通续费。请到官方页面确认当前状态，过去的费用是否退还需要另外核实。',
    'passwordless': '免密支付是付款时可能不用再次输密码，并不一定代表每个月都扣钱。请另查是否签约自动扣款。',
}
ANALOGIES = {
    'none':'',
    'monthly':'可以把它想成按月交的服务费：约定还在时，到了时间可能继续扣钱。',
    'yearly':'可以把它想成按年交的服务费：一年到期后，可能再收下一年的钱。',
    'trial':'就像先试用一段时间，到期后可能开始收费；免费不一定会一直免费。',
}

# Keep the local parser and the LLM evidence validator on the same conservative
# vocabulary. A negated phrase must never count as a positive renewal signal.
RENEWAL_NEGATIVE_PHRASES = (
    '已关闭自动续费', '自动续费已关闭', '已取消自动续费', '自动扣费已关闭',
    '未开通自动续费', '未开启自动续费', '不自动续费', '不会自动续费',
    '不再自动续费', '没有自动续费', '没有开启自动续费', '没有开通自动续费',
    '未设置自动续费', '已停止自动续费', '续费已关闭', '已取消续订',
    '不会继续扣费', '不再续费', '不会续费', '不续费', '无需续费',
    '不连续包月', '没有连续包月', '非连续包月', '不再连续包月',
    '不连续包年', '没有连续包年', '非连续包年', '不再连续包年',
    '不是自动续费', '并非自动续费', '未设置自动扣款', '未开通自动扣款',
    '自动续订已关闭', '已关闭自动续订', '不自动续订', '不会自动续订',
    '自动续费未开启', '没有连续续费',
)
RENEWAL_POSITIVE_PHRASES = (
    '连续包月', '连续包年', '每月自动扣', '每年自动扣', '已开启自动续费',
    '已开通自动续费', '已开启自动续期', '到期自动续费', '将自动续费',
    '自动续费已开启', '每月续费', '每年续费', '按月续费', '按年续费',
    '自动扣款已开通', '自动续订已开启', '每月自动续费', '每年自动续费',
    '续费已开启', '已开通自动续订', '自动续费开启',
)

_MONEY_NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?'
_MONEY_PATTERN = re.compile(
    rf'(?<![\d.,])(?:[¥￥]\s*(?P<symbol>{_MONEY_NUMBER})'
    rf'|人民币\s*(?P<rmb_prefix>{_MONEY_NUMBER})'
    rf'|(?P<suffix>{_MONEY_NUMBER})\s*(?:元|块钱|块|人民币|CNY|RMB)(?![A-Za-z]))',
    re.IGNORECASE,
)


def money_mentions(text):
    """Return every explicit currency amount as Decimal; repeated mentions remain distinct."""
    values = []
    for match in _MONEY_PATTERN.finditer(text):
        raw = match.group('symbol') or match.group('rmb_prefix') or match.group('suffix')
        value = Decimal(raw.replace(',', ''))
        if value <= Decimal('10000000'):
            values.append(value)
    return values


def money_values(text):
    """Return explicit currency amounts as floats, preserving repeated mentions as ambiguity."""
    return [float(value) for value in money_mentions(text)]


def _negation_kind(text, position):
    """Return 'single', 'double', or None for negation immediately before a renewal phrase."""
    prefix = text[max(0, position - 12):position]
    prefix = re.sub(r'[\s，,：:、]+$', '', prefix)
    if re.search(r'(?:不是没有|并非没有|不是未|并非未|不是不|并非不)$', prefix):
        return 'double'
    if re.search(r'(?:并非|不是|不再|不会|没有|未曾|未|没|不|非|无|无需|不必)$', prefix):
        return 'single'
    return None


def renewal_status_evidence(text):
    """Return (status, negative evidence, positive evidence); conflicts remain unknown."""
    negative_hits = []
    positive_hits = []
    ambiguous = False

    for phrase in sorted(RENEWAL_NEGATIVE_PHRASES, key=len, reverse=True):
        for match in re.finditer(re.escape(phrase), text):
            negation = _negation_kind(text, match.start())
            if negation is None:
                negative_hits.append(phrase)
            else:
                # For example, "不是没有连续包月" is not safe to reduce to a boolean.
                ambiguous = True

    for phrase in sorted(RENEWAL_POSITIVE_PHRASES, key=len, reverse=True):
        for match in re.finditer(re.escape(phrase), text):
            negation = _negation_kind(text, match.start())
            if negation == 'double':
                ambiguous = True
            elif negation == 'single':
                negative_hits.append(phrase)
            else:
                positive_hits.append(phrase)

    negative_hits = list(dict.fromkeys(negative_hits))
    positive_hits = list(dict.fromkeys(positive_hits))
    if ambiguous or (negative_hits and positive_hits):
        status = None
    elif negative_hits:
        status = False
    elif positive_hits:
        status = True
    else:
        status = None
    return status, negative_hits, positive_hits



def analyze(text):
    if not isinstance(text, str) or not text.strip() or len(text)>12000:
        raise ValueError('请提供 1 至 12000 字的账单文字。')
    text = text.strip()
    found = [s for s in SERVICES if s.lower() in text.lower()]
    # Longest names win over prefixes such as 淘宝.
    found = [s for s in found if not any(s!=t and s in t for t in found)]
    service = found[0] if len(found)==1 else '待确认服务'
    category = SERVICES.get(service, '待确认')
    platform = '支付宝' if '支付宝' in text else ('微信支付' if '微信' in text else '未说明')
    if service=='待确认服务' and not found and ('会员' not in text and '增值' not in text):
        if '软件订阅' in text: category = '软件订阅'
        elif '套餐' in text: category = '手机服务'
    amounts = money_values(text)
    amount = amounts[0] if len(amounts)==1 else None
    auto, negatives, positives = renewal_status_evidence(text)
    period = '月' if re.search('连续包月|每月|按月',text) else ('年' if re.search('连续包年|每年|按年',text) else None)
    trial = '试用' in text
    passwordless = '免密' in text
    evidence = {'service':service if service!='待确认服务' else None,'auto': negatives+positives,'amount':amounts}
    risks=[]
    def add(code,level,message,source): risks.append({'code':code,'level':level,'message':message,'source':source})
    if re.search(r'验证码|安全账户|解冻|远程控制|屏幕共享|转账.*取消|取消.*转账',text):
        add('suspicious_request','高','信息中出现需要警惕的要求，但仅凭这段文字不能判定真伪。','输入文字')
    if service=='待确认服务':
        add('unknown_service','待核实','服务名称需要进一步核对；陌生名称本身不等于诈骗。','输入文字或用户补充')
    if trial and auto is not False:
        add('trial_renewal','注意','试用到期后可能收费，需要确认到期日期和价格。','输入文字')
    if auto is True:
        add('recurring','注意','这份信息显示会继续自动扣费，请确认现在是否仍然需要。','输入文字')
    if len(amounts)>1 or len(found)>1 or (positives and negatives):
        add('ambiguous','待核实','文字含多个金额、服务或冲突状态。请拆成一笔账单再核对。','输入文字')
    if re.search('退款|退回|收入|收款|支付失败|未支付|待支付', text):
        amount = None
        add('not_confirmed_debit','待核实','这可能是退款、收入或未完成的支付，不能当作已扣款。','输入文字')
    if auto is None:
        why = '仅凭这些文字，还不能确定以后是否会继续扣钱。会员或免密支付不一定就是自动续费。'
    elif auto:
        cost = f'{amount:g} 元' if amount is not None else '约定的费用'
        cycle = f'每{period}' if period else '到约定时间'
        why = f'这份信息显示自动续费已开启，{cycle}可能继续扣{cost}，通常不需要您再次确认。实际金额请以服务页面为准。'
    else:
        why = '这份信息显示续费已关闭或未开通。请以官方页面的当前状态为准。'
    ids=['verify']
    codes={r['code'] for r in risks}
    if 'suspicious_request' in codes: ids.insert(0,'phishing')
    if auto: ids+=['renew','cancel']
    if auto is False: ids+=['paid']
    if trial: ids+=['trial']
    if passwordless: ids+=['passwordless']
    if 'unknown_service' in codes: ids+=['contact']
    analogy='trial' if trial else ('monthly' if auto and period=='月' else ('yearly' if auto and period=='年' else 'none'))
    return {'service':service,'category':category,'platform':platform,'amount':amount,'currency':'CNY',
            'auto_renew':auto,'period':period,'evidence':evidence,'risk_level':'高' if any(r['level']=='高' for r in risks) else ('注意' if risks else '未发现规则命中'),
            'risks':risks,'what':f'这可能是{service}的{category}相关信息。' if service!='待确认服务' else '暂时无法确认服务名称，请先核对收款方和订单详情。',
            'why':why,'analogy':ANALOGIES[analogy],'analogy_id':analogy,'advice_ids':ids,'next_steps':[ADVICE[i] for i in ids],
            'mode':'本地规则演示','llm_status':'未启用','notice':'这是根据您提供的内容作出的解释，不代表已经关闭服务，也不能证明账单真实。'}


def summarize(results):
    """Current-session totals only; no annualization, inference of history or dedup guesses."""
    categories={}
    for r in results:
        entry=categories.setdefault(r['category'],{'count':0,'known_amount_total':0,'unknown_amount_count':0})
        entry['count']+=1
        if r['amount'] is None: entry['unknown_amount_count']+=1
        else: entry['known_amount_total']=round(entry['known_amount_total']+r['amount'],2)
    return {'categories':categories,'count':len(results),'scope':'仅统计本次逐笔输入，金额不代表月支出；重复输入会重复计数。'}
