#ifndef QS_CAMERA_H
#define QS_CAMERA_H

/**
 * @file qs_camera.h
 * @brief QS相机动态链接库头文件。
 *
 * This header file uses utf-8 encoding for comments.
 * 所有的中文注释都使用utf-8编码。
 */

#include "qs_errorcodes.h"

#include <stdint.h>
#include <stddef.h>
#define API_PUBLIC __attribute((visibility("default")))
#ifdef __cplusplus
extern "C" {
#endif
	/**
	 * @enum QsCameraCommand
	 * @brief 相机控制命令枚举。
	 */
	typedef enum
	{
		/**
		 * @brief 获取曝光时间最大值，参数类型为 int。
		 */
		QS_CAMERA_GET_EXPOSURE_MAX,
		/**
		 * @brief 获取曝光时间最小值，参数类型为 int。
		 */
		QS_CAMERA_GET_EXPOSURE_MIN,
		/**
		 * @brief 设置曝光时间，参数类型为 int。
		 */
		QS_CAMERA_SET_EXPOSURE,
		/**
		 * @brief 获取曝光时间，参数类型 int。
		 */
		QS_CAMERA_GET_EXPOSURE,
		/**
		 * @brief 获取是否有光源灯，参数类型 bool。
		 */
		QS_CAMERA_HAS_LAMP,
		/**
		 * @brief 设置光源打开/关闭，参数类型 bool。
		 */
		QS_CAMERA_SET_LAMP,
		/**
		 * @brief 获取光源是否打开，参数类型 bool。
		 */
		QS_CAMERA_GET_LAMP,
		/**
		 * @brief 获取相机名，参数类型 const char*。
		 */
		QS_CAMERA_GET_NAME
	}QsCameraCommand;
	/**
	 * @brief 相机数据回调函数类型。
	 * @param data 图像数据指针。
	 * @param size data大小。
	 * @param 外部上下文。
	 */
	typedef void (*cameraCallback)(const uint8_t* data, const size_t size, void* context);
	/**
	 * @brief 相机上下文，用于管理相机资源。
	 */
	typedef struct QsCameraContextTag QsCameraContext;
	/**
	 * @brief 枚举相机设备。
	 * @param cameras 相机数组，用于存储枚举结果，需要传入nullptr，在函数中申请内存，由releaseQsCamera释放。
	 * @param size 相机数量。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes enumQsCamera(QsCameraContext*** cameras, int* size);
	/**
	 * @brief 打开相机设备。
	 * @param camera 相机指针。
	 * @param isAsync 是否异步获取图像。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes openQsCamera(QsCameraContext* camera, const bool isAsync);
	/**
	 * @brief 关闭相机设备。
	 * @param camera 相机指针。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes closeQsCamera(QsCameraContext* camera);
	/**
	 * @brief 释放相机资源。
	 * @param cameras 相机指针数组。
	 * @param size 相机数量。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes releaseQsCamera(QsCameraContext** cameras, const int size);
	/**
	 * @brief 获取一帧相机数据。
	 * @param camera 相机指针。
	 * @param size 图像数据大小。
	 * @return 返回图像数据指针，该指针内存由相机上下文管理。
	 */
	API_PUBLIC uint8_t* getQsData(QsCameraContext* camera, size_t* size);
	/**
	 * @brief 注册相机回调函数。
	 * @param camera 相机指针。
	 * @param callback 回调函数指针。
	 * @param context 外部上下文。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes registerQsCameraCallback(QsCameraContext* camera, cameraCallback callback, void* context);
	/**
	 * @brief 控制相机设备。
	 * @param camera 相机指针。
	 * @param command 控制命令，参考QSCameraCommand。
	 * @param value 命令参数值指针。
	 * @return 返回QSErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes controlQsCamera(QsCameraContext* camera, const QsCameraCommand command, void* value);

#ifdef __cplusplus
}
#endif

#endif
