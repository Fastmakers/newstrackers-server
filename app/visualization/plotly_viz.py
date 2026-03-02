"""
Plotly Visualization - Create interactive charts
"""

from typing import List

import pandas as pd
import plotly.graph_objects as go

from app.schemas.data_models import MonthlySentiment, RadarChart


def create_radar_chart(radar_data: RadarChart) -> go.Figure:
    """
    Create a radar chart for 5-dimension company scoring
    
    Args:
        radar_data: RadarChart object with labels and scores
    
    Returns:
        Plotly figure
    """
    fig = go.Figure(data=go.Scatterpolar(
        r=radar_data.scores,
        theta=radar_data.labels,
        fill='toself',
        name='회사 평가',
        line_color='#1f77b4',
        fillcolor='rgba(31, 119, 180, 0.3)'
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 10],
                tickfont=dict(size=10),
            ),
            angularaxis=dict(
                tickfont=dict(size=11),
            ),
        ),
        showlegend=True,
        height=500,
        font=dict(family="Arial", size=12),
        title={
            'text': '5대 지표 분석 (Radar Chart)',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 16}
        },
        hovermode='closest',
        plot_bgcolor='rgba(240, 240, 240, 0.5)',
    )
    
    return fig


def create_sentiment_heatmap(monthly_sentiments: List[MonthlySentiment]) -> go.Figure:
    """
    Create a heatmap showing monthly sentiment trends
    
    Args:
        monthly_sentiments: List of MonthlySentiment objects
    
    Returns:
        Plotly figure
    """
    if not monthly_sentiments:
        # Return empty figure
        return go.Figure()
    
    # Convert to DataFrame
    data = []
    for item in monthly_sentiments:
        data.append({
            'month': item.month,
            'intensity': item.intensity,
            'sentiment': item.score,
            'issue': item.issue
        })
    
    df = pd.DataFrame(data)
    
    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=[df["sentiment"].tolist()],
        x=df["month"].tolist(),
        y=["감정 지수"],
        colorscale='RdYlGn',
        colorbar=dict(title='감정 점수<br>(0=부정, 5=중립, 10=긍정)'),
        text=[df["issue"].tolist()],
        textfont=dict(color='black', size=10),
        hovertemplate='<b>%{x}</b><br>감정: %{z:.1f}<br>이슈: %{text}<extra></extra>',
    ))
    
    # Add intensity as secondary visualization
    fig.add_trace(go.Scatter(
        x=df['month'],
        y=[0] * len(df),
        marker=dict(
            size=df['intensity'] * 3,
            color=df['intensity'],
            colorscale='Viridis',
            line=dict(width=1, color='white'),
        ),
        mode='markers',
        name='뉴스 강도',
        yaxis='y2',
        hovertemplate='<b>%{x}</b><br>강도: %{customdata}<extra></extra>',
        customdata=df['intensity']
    ))
    
    fig.update_layout(
        title={
            'text': '월별 감정 지수 분석 (Sentiment Heatmap)',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 16}
        },
        xaxis_title='기간',
        yaxis_title='감정 분석',
        height=400,
        hovermode='x unified',
        plot_bgcolor='rgba(240, 240, 240, 0.5)',
        paper_bgcolor='white',
        font=dict(family="Arial", size=12),
        yaxis2=dict(
            title='뉴스 강도',
            overlaying='y',
            side='right',
            range=[0, max(df['intensity']) + 2]
        ),
        showlegend=True,
        margin=dict(l=100, r=100, t=80, b=80),
    )
    
    return fig


def create_trend_timeline(monthly_sentiments: List[MonthlySentiment]) -> go.Figure:
    """
    Create a line chart showing trend over time
    
    Args:
        monthly_sentiments: List of MonthlySentiment objects
    
    Returns:
        Plotly figure
    """
    if not monthly_sentiments:
        return go.Figure()
    
    data = []
    for item in monthly_sentiments:
        data.append({
            'month': item.month,
            'sentiment': item.score,
            'intensity': item.intensity,
            'issue': item.issue
        })
    
    df = pd.DataFrame(data)
    
    fig = go.Figure()
    
    # Add sentiment line
    fig.add_trace(go.Scatter(
        x=df['month'],
        y=df['sentiment'],
        mode='lines+markers',
        name='감정 지수',
        line=dict(color='#1f77b4', width=3),
        marker=dict(size=8),
        fill='tozeroy',
        fillcolor='rgba(31, 119, 180, 0.2)',
        hovertemplate='<b>%{x}</b><br>감정: %{y:.1f}<extra></extra>'
    ))
    
    # Add intensity as bar chart
    fig.add_trace(go.Bar(
        x=df['month'],
        y=df['intensity'],
        name='뉴스 강도',
        marker=dict(color='rgba(255, 127, 14, 0.5)'),
        yaxis='y2',
        hovertemplate='<b>%{x}</b><br>강도: %{y}<extra></extra>'
    ))
    
    fig.update_layout(
        title='산업 트렌드 타임라인',
        xaxis_title='기간',
        yaxis_title='감정 지수',
        yaxis2=dict(
            title='뉴스 강도',
            overlaying='y',
            side='right'
        ),
        height=400,
        hovermode='x unified',
        plot_bgcolor='rgba(240, 240, 240, 0.5)',
        font=dict(family="Arial", size=12),
    )
    
    return fig
