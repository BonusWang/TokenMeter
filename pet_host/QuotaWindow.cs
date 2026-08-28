using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace TokenMeter.Pet;

internal sealed class QuotaWindow : Window
{
    private bool shuttingDown;
    private readonly TextBlock provider = new();
    private readonly TextBlock primary = new() { FontSize = 25, FontWeight = FontWeights.SemiBold };
    private readonly TextBlock secondary = new() { TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock status = new() { Foreground = Brushes.SandyBrown, TextWrapping = TextWrapping.Wrap };

    public QuotaWindow(bool demo, Action openPanel, Action unpin, Action credits)
    {
        Title = demo ? "TokenMeter 额度 · 演示数据" : "TokenMeter 额度";
        Width = 244;
        Height = 236;
        WindowStyle = WindowStyle.ToolWindow;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;
        Topmost = true;
        Background = new SolidColorBrush(Color.FromRgb(29, 29, 29));
        Foreground = Brushes.WhiteSmoke;
        var stack = new StackPanel { Margin = new Thickness(14) };
        foreach (var block in new[] { provider, primary, secondary, status })
        {
            block.Margin = new Thickness(0, 0, 0, 7);
            stack.Children.Add(block);
        }
        var open = new Button { Content = "查看用量面板", Padding = new Thickness(5) };
        open.Click += (_, _) => openPanel();
        stack.Children.Add(open);
        var source = new Button { Content = "角色 / 动画来源：VPet · 非商业试用", FontSize = 10,
            Margin = new Thickness(0, 8, 0, 0), Padding = new Thickness(0), Background = Brushes.Transparent,
            BorderThickness = new Thickness(0), Foreground = Brushes.LightGray };
        source.Click += (_, _) => credits();
        stack.Children.Add(source);
        Content = stack;
        // 用户关闭只取消常驻，不关闭桌宠；主应用退出时 Owner 会一并销毁窗口。
        Closing += (_, e) => { if (!shuttingDown) { e.Cancel = true; Hide(); unpin(); } };
        SetUsage(demo ? "Codex · 演示数据" : "等待用量数据", demo ? "剩余 65%" : "--", "", "");
    }

    internal void SetUsage(string provider, string primary, string secondary, string status)
    {
        this.provider.Text = provider;
        this.primary.Text = primary;
        this.secondary.Text = secondary;
        this.status.Text = status;
    }

    internal void CloseForShutdown() { shuttingDown = true; Close(); }
}
