#ifndef QS_FILEIO_H
#define QS_FILEIO_H

/**
 * @file qs_fileio.h
 * @brief QS文件读写动态链接库头文件。
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
	 * @brief 读取qs(图像文件)。
	 * @param path qs文件路径。
	 * @param data 文件数据指针，需要传入nullptr，在函数中申请内存，并使用freeQsData释放。
	 * @param size 返回文件数据长度。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes loadQsFile(const char* path, uint8_t** data, size_t* size);
	/**
	 * @brief 保存qs(图像文件)。
	 * @param path qs文件路径。
	 * @param data 文件数据指针。
	 * @param size 文件数据长度。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes saveQsFile(const char* path, const uint8_t* data, const size_t size);
	/**
	 * @brief 读取qsbs(相机标定文件)。
	 * @param path qsbs文件路径。
	 * @param data 文件数据指针，需要传入nullptr，在函数中申请内存，并使用freeQsData释放。
	 * @param size 返回文件数据长度。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes loadQsbsFile(const char* path, uint8_t** data, size_t* size);
	/**
	* @brief 释放内存。
	* @param ptr 需要释放的指针。
	* @return 返回QsErrorcodes错误代码。
	*/
	API_PUBLIC QsErrorcodes freeQsData(void* ptr);
#ifdef __cplusplus
}
#endif

#endif
