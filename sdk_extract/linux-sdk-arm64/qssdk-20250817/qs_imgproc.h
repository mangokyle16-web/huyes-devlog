#ifndef QS_IMGPROC_H
#define QS_IMGPROC_H

/**
 * @file qs_imgproc.h
 * @brief QS图像处理动态链接库头文件。
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
	 * @brief 图像处理上下文，用于管理资源。
	 */
	typedef struct QsImgprocContextTag QsImgprocContext;
	/**
	 * @brief 初始化上下文。
	 * @param context 图像处理上下文，需要传入nullptr，在函数中申请内存，由deinitQsImgproc释放。
	 * @param qsbsData 通过loadQsbsFile读取的qsbs文件数据指针。
	 * @param qsbsSize qsbs文件数据大小。
	 */
	API_PUBLIC QsErrorcodes initQsImgproc(QsImgprocContext** context, const uint8_t* qsbsData, const size_t qsbsSize);
	/**
	 * @brief qs文件转灰度图像。
	 * @param context 图像处理上下文。
	 * @param qsData 通过loadQsFile读取的qs文件数据指针。
	 * @param qsSize qs文件数据大小。
	 * @param grayData 灰度图像数据指针，维度[height][width]，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param width 灰度图像的宽。
	 * @param height 灰度图像的高。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qsToGray(
		QsImgprocContext* context, const uint8_t* qsData, const size_t qsSize, 
		uint8_t** grayData, int* width, int* height);
	/**
	 * @brief qs文件转rgb图像。
	 * @param context 图像处理上下文。
	 * @param qsData 通过loadQsFile读取的qs文件数据指针。
	 * @param qsSize qs文件数据大小。
	 * @param rgbData rgb图像数据指针，维度[height][width][rgb]，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param width rgb图像的宽。
	 * @param height rgb图像的高。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qsToRgb(
		QsImgprocContext* context, const uint8_t* qsData, const size_t qsSize, 
		uint8_t** rgbData, int* width, int* height);
	/**
	 * @brief 图像处理上下文资源释放函数。
	 * @param context 图像处理上下文。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes deinitQsImgproc(QsImgprocContext* context);
#ifdef __cplusplus
}
#endif

#endif
