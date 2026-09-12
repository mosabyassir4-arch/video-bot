    ydl_opts = {
        'outtmpl': 'temp_file.%(ext)s',
        'progress_hooks': [progress_hook],
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        # تخطي فحص البوت عبر محاكاة عميل التلفاز والويب المطور
        'extractor_args': {
            'youtube': {
                'player_client': ['tv', 'mweb'],
                'player_skip': ['web', 'configs']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/6.0 TV Safari/538.1',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }
