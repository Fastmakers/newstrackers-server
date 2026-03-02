"""
WordCloud Visualization - Create custom colored word clouds
"""

from typing import List

import plotly.graph_objects as go

from app.core.constants import KEYWORD_CATEGORIES
from app.schemas.data_models import Keyword


def create_wordcloud(keywords: List[Keyword]) -> go.Figure:
    """
    Create an interactive word cloud visualization using Plotly
    Words are colored by category (tech, corp, policy)
    
    Args:
        keywords: List of Keyword objects
    
    Returns:
        Plotly figure with word cloud
    """
    
    if not keywords:
        # Return empty figure
        fig = go.Figure()
        fig.add_annotation(text="No keywords to display")
        return fig
    
    # Prepare data
    words = []
    sizes = []
    colors_list = []
    hover_texts = []
    
    # Map category to color
    category_colors = {
        "tech": KEYWORD_CATEGORIES["tech"]["color"],
        "corp": KEYWORD_CATEGORIES["corp"]["color"],
        "policy": KEYWORD_CATEGORIES["policy"]["color"],
    }
    
    category_names = {
        "tech": "기술/혁신",
        "corp": "기업/사람",
        "policy": "정책/규제",
    }
    
    for keyword in keywords:
        words.append(keyword.word)
        sizes.append(keyword.weight * 0.5 + 10)  # Scale for marker size
        color = category_colors.get(keyword.type, "#999999")
        colors_list.append(color)
        
        hover_text = (
            f"<b>{keyword.word}</b><br>"
            f"Category: {category_names.get(keyword.type, 'Unknown')}<br>"
            f"Weight: {keyword.weight}"
        )
        hover_texts.append(hover_text)
    
    # Create scatter plot as wordcloud
    # Position words randomly in 2D space for word cloud effect
    import math
    import random
    
    random.seed(42)
    
    positions_x = []
    positions_y = []
    
    for i, keyword in enumerate(keywords):
        # Spiral arrangement for better distribution
        angle = (i / len(keywords)) * 2 * math.pi
        radius = 5 + (i / len(keywords)) * 35
        
        x = radius * math.cos(angle) + random.uniform(-2, 2)
        y = radius * math.sin(angle) + random.uniform(-2, 2)
        
        positions_x.append(x)
        positions_y.append(y)
    
    fig = go.Figure()
    
    # Add scatter points (words)
    fig.add_trace(go.Scatter(
        x=positions_x,
        y=positions_y,
        mode='markers+text',
        marker=dict(
            size=sizes,
            color=colors_list,
            opacity=0.8,
            line=dict(width=1, color='white'),
        ),
        text=words,
        textposition='middle center',
        textfont=dict(
            size=[s / 2 for s in sizes],  # Text size proportional to word size
            family='Arial',
            color='white',
        ),
        hovertext=hover_texts,
        hoverinfo='text',
        showlegend=False,
        name='Keywords',
    ))
    
    # Add legend manually
    for category, color in category_colors.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode='markers',
            marker=dict(size=15, color=color),
            name=category_names[category],
            showlegend=True,
            hoverinfo='none'
        ))
    
    fig.update_layout(
        title={
            'text': '산업 키워드 맵 (Word Cloud)',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 16}
        },
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            range=[-50, 50],
        ),
        yaxis=dict(
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            range=[-50, 50],
        ),
        plot_bgcolor='rgba(240, 245, 250, 0.5)',
        paper_bgcolor='white',
        height=500,
        hovermode='closest',
        showlegend=True,
        legend=dict(
            x=0.02,
            y=0.98,
            bgcolor='rgba(255, 255, 255, 0.8)',
            bordercolor='#cccccc',
            borderwidth=1
        ),
        margin=dict(l=20, r=20, t=80, b=20),
        font=dict(family="Arial", size=11),
    )
    
    return fig


def create_keyword_bar_chart(keywords: List[Keyword], top_n: int = 15) -> go.Figure:
    """
    Create a bar chart of top keywords by weight
    
    Args:
        keywords: List of Keyword objects
        top_n: Number of top keywords to display
    
    Returns:
        Plotly figure
    """
    
    if not keywords:
        return go.Figure()
    
    # Sort and take top N
    sorted_keywords = sorted(keywords, key=lambda k: k.weight, reverse=True)[:top_n]
    
    # Map category to color
    category_colors = {
        "tech": KEYWORD_CATEGORIES["tech"]["color"],
        "corp": KEYWORD_CATEGORIES["corp"]["color"],
        "policy": KEYWORD_CATEGORIES["policy"]["color"],
    }
    
    words = [k.word for k in sorted_keywords]
    weights = [k.weight for k in sorted_keywords]
    colors = [category_colors.get(k.type, "#999999") for k in sorted_keywords]
    
    fig = go.Figure(data=[
        go.Bar(
            y=words,
            x=weights,
            orientation='h',
            marker=dict(
                color=colors,
                line=dict(color='white', width=1)
            ),
            text=[f'{w:.0f}' for w in weights],
            textposition='outside',
            hovertemplate='<b>%{y}</b><br>Weight: %{x:.0f}<extra></extra>',
        )
    ])
    
    fig.update_layout(
        title='상위 키워드 (가중치 기준)',
        xaxis_title='가중치 (Weight)',
        yaxis_title='키워드',
        height=400 + (len(words) // 3) * 20,
        plot_bgcolor='rgba(240, 240, 240, 0.5)',
        font=dict(family="Arial", size=12),
        margin=dict(l=150, r=100, t=80, b=60),
        showlegend=False,
        hovermode='closest',
    )
    
    return fig
