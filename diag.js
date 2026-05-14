// Find recording items on Tencent Meeting recordings page
(() => {
    const results = [];

    // Try to find recording items by class
    const allElements = document.querySelectorAll('*');
    const candidates = [];
    for (const el of allElements) {
        if (el.children.length > 0 && el.offsetHeight > 50) {
            const text = el.textContent.trim();
            if (text.includes('录制') || text.includes('会议') || text.includes('文件')) {
                const cls = typeof el.className === 'string' ? el.className : '';
                if (cls && cls.length > 5 && cls.length < 200) {
                    candidates.push({
                        tag: el.tagName,
                        cls: cls.slice(0, 100),
                        children: el.children.length,
                        text: text.slice(0, 80)
                    });
                }
            }
        }
    }

    results.push('Candidates: ' + candidates.length);
    candidates.slice(0, 15).forEach(c => {
        results.push(c.tag + ' .' + c.cls.split(' ')[0] + ' [' + c.children + ' children] ' + c.text);
    });

    // Look for download buttons
    const downloadBtns = [];
    document.querySelectorAll('button, a').forEach(el => {
        const text = el.textContent.trim();
        if (text.includes('下载') || text.includes('导出') || text.includes('export') || text.includes('download')) {
            downloadBtns.push(text.slice(0, 30));
        }
    });
    results.push('Download buttons: ' + downloadBtns.join(', '));

    return results.join('\n');
})();
