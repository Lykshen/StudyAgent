# StudyAgent 手机 App

手机 App 连接电脑上运行的 StudyAgent。题库、判题、数据都在电脑上，手机负责学习、做题、测试、和智能体对话。

## 先在电脑上打开「允许手机连接」

电脑端 StudyAgent →「设置 → 设备与互通」→ 勾选「允许手机连接」（Windows 弹出权限窗口时点「是」）。记下「在手机上填」里标着「优先用这个」的地址（例如 `http://192.168.1.20:8765`）和访问码。

## 不用安装：添加到主屏幕（马上能用）

- **iPhone / iPad**：用 Safari 打开局域网地址 → 分享按钮 →「添加到主屏幕」。之后从桌面图标打开，是全屏的 App 界面。
- **安卓**：用 Chrome 打开局域网地址 → 右上角菜单 →「添加到主屏幕」。

## 安卓 App（APK）

需要一台装了 [Node.js 18+](https://nodejs.org) 和 [Android Studio](https://developer.android.com/studio) 的电脑：

```
cd mobile
npm install
npm run android        # 生成安卓工程、图标，并用 Android Studio 打开
```

在 Android Studio 里：菜单 Build → Build App Bundle(s) / APK(s) → Build APK(s)，生成的 `app-debug.apk` 发到手机安装即可。要上架或长期分发，请在 Android Studio 里用自己的签名打 release 包。

## iPhone App

需要 Mac 和 Xcode：`npm install && npx cap add ios && npx cap sync ios && npx cap open ios`，在 Xcode 里选择开发者账号后运行到手机。

## 使用

第一次打开 App 填电脑的地址（如 `192.168.1.20:8765`），连上后输入访问码。之后打开 App 会自动连接上次的电脑；要换电脑，在「设置 → 设备与互通」里点「连接其它电脑」。

> App 和电脑之间走局域网 HTTP，只在自己家或可信的 Wi-Fi 里使用。
