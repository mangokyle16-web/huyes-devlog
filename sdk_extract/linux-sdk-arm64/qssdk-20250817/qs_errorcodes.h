#ifndef QS_ERRORCODES_H
#define QS_ERRORCODES_H

/**
 * @file qs_errorcodes.h
 * @brief qs错误码头文件。
 *
 * This header file uses GB2312 encoding for comments.
 * 所有的中文注释都使用GB2312编码。
 */

 /**
  * @brief qs错误码枚举。
  */
typedef enum
{
    /**
     * @brief 操作成功，无错误发生。
     */
    QS_ERR_SUCCESS,
    /**
     * @brief 无相机设备。
     */
    QS_ERR_NO_CAMERA,
    /**
    * @brief 无效上下文。
    */
    QS_ERR_INVALID_CONTEXT,
    /**
     * @brief 无效数据。
     */
    QS_ERR_INVALID_DATA,
    /**
     * @brief 无效相机指令。
     */
    QS_ERR_INVALID_CAMERA_COMMAND,
    /**
     * @brief 文件打开失败。
     */
    QS_ERR_FILE_OPEN_FAILED,
    /**
     * @brief 文件读失败。
     */
    QS_ERR_FILE_READ_FAILED,
    /**
     * @brief 文件写失败。
     */
    QS_ERR_FILE_WRITE_FAILED,
    /**
     * @brief 无效文件。
     */
    QS_ERR_INVALID_FILE,
    /**
     * @brief 光谱分辨率不匹配。
     */
    QS_ERR_RESOLUTION_MISMATCH
}QsErrorcodes;

/**
 * @brief 将QsErrorcodes枚举值转换为对应的错误字符串。
 *
 * @param code 要转换的错误代码。
 * @return 返回一个描述错误的字符串。
 */
inline const char* qsErrorToString(QsErrorcodes code)
{
    switch (code)
    {
    case QS_ERR_SUCCESS:
        return "no error";
    case QS_ERR_NO_CAMERA:
        return "no camera";
    case QS_ERR_INVALID_CONTEXT:
        return "invalid context";
    case QS_ERR_INVALID_DATA:
        return "invalid data";
    case QS_ERR_INVALID_CAMERA_COMMAND:
        return "invalid camera command";
    case QS_ERR_FILE_OPEN_FAILED:
        return "file open failed";
    case QS_ERR_FILE_READ_FAILED:
        return "file read failed";
    case QS_ERR_FILE_WRITE_FAILED:
        return "file write failed";
    case QS_ERR_INVALID_FILE:
        return "invalid file";
    case QS_ERR_RESOLUTION_MISMATCH:
        return "spectral resolution mismatch";
    default:
        return "unknown error";
    }
}

#endif