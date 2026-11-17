"""CommonMark rendering with tables and an explicit HTML sanitization boundary."""
from functools import lru_cache
from markdown_it import MarkdownIt
import nh3

PARSER = MarkdownIt('commonmark', {'html': False}).enable(['table', 'strikethrough'])
TAGS = {'p','br','hr','h1','h2','h3','h4','h5','h6','strong','em','s','ul','ol','li',
        'blockquote','pre','code','a','table','thead','tbody','tr','th','td'}


@lru_cache(maxsize=128)
def render_markdown(text: str) -> str:
    return nh3.clean(PARSER.render(text[:30000]), tags=TAGS,
                     attributes={'a':{'href','title'}, 'ol':{'start'}},
                     url_schemes={'https','http','mailto'},
                     link_rel='noopener noreferrer', strip_comments=True)
